"""
Daily Data Update (Tiingo prices + SEC EDGAR fundamentals)
==========================================================
Run after the close (the workflow runs it before the portfolio manager).

1. Company list: refresh from Tiingo. New listings are added with full
   history; ticker changes (same Tiingo permaTicker, new ticker) are renamed
   everywhere, including the live ledger and universe cache; companies that
   stopped trading are marked delisted.
2. Prices: for every active security fetch the bars since its last stored bar.
   If a new bar carries a dividend or split - or Tiingo revised past adjusted
   prices - the full history is re-downloaded, so stored prices always match
   Tiingo's adjustment. Market holidays simply produce no new bar.
3. Fundamentals: companies that filed a 10-K/10-Q since the last run (SEC daily
   index) get their company facts reloaded; new versions are added point-in-time.
4. Leaders factor history (when SCREEN_NAME = 'leaders'): new quarters and
   completed 12-month returns are added, so the screen's weights stay current.

Fails (exit code 1, so the workflow does not generate orders) when SPY has no
bar for the latest completed session or too few stocks updated.

Usage:
    python daily_update.py             # normal run
    python daily_update.py --dry-run   # show what would be fetched
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import argparse
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from logging_setup import setup_logging
import secure_config  # noqa: F401  (loads .env)

logger = logging.getLogger('daily_update')

PROJECT_ROOT = Path(__file__).resolve().parent
EDGAR_STATE_FILE = PROJECT_ROOT / 'data' / 'cache' / 'edgar_state.json'
MARKET_TZ = ZoneInfo('America/New_York')
SESSION_READY = (18, 0)          # Tiingo end-of-day data is complete by ~18:00 ET
HISTORY_START = '2008-01-01'
OVERLAP_DAYS = 10                # re-fetched bars used to detect revised adjustments
MIN_UPDATED_FRACTION = 0.9       # of active stocks that must have the target session


def last_completed_session_candidate(now: datetime = None) -> pd.Timestamp:
    """Latest weekday whose end-of-day data should be available (holidays found from data)"""
    now = (now or datetime.now(MARKET_TZ)).astimezone(MARKET_TZ)
    day = pd.Timestamp(now.date())
    if (now.hour, now.minute) < SESSION_READY:
        day -= pd.Timedelta(days=1)
    while day.weekday() >= 5:
        day -= pd.Timedelta(days=1)
    return day


def rename_in_live_files(old: str, new: str):
    """Keep the ledger and the universe cache in step with a ticker change"""
    import daily_portfolio_manager as dpm
    state = dpm.STATE_FILE
    if state.exists():
        data = json.loads(state.read_text())
        if old in data.get('positions', {}):
            data['positions'][new] = data['positions'].pop(old)
            logger.warning("Ledger position renamed %s -> %s", old, new)
        if old in data.get('swap_streaks', {}):
            data['swap_streaks'][new] = data['swap_streaks'].pop(old)
        state.write_text(json.dumps(data, indent=2))
    cache = dpm.UNIVERSE_CACHE_FILE
    if cache.exists():
        data = json.loads(cache.read_text())
        data['symbols'] = [new if s == old else s for s in data.get('symbols', [])]
        for row in data.get('scores', []):
            if row.get('symbol') == old:
                row['symbol'] = new
        cache.write_text(json.dumps(data, indent=2, default=float))


class TiingoDailyUpdater:
    def __init__(self, db, tiingo, sec=None):
        self.db = db
        self.tiingo = tiingo
        self.sec = sec

    # ------------------------------------------------------- company list
    def _make_room(self, symbol: str) -> bool:
        """
        Free `symbol` for an active company: a delisted company still stored
        under it moves to 'SYMBOL~YEAR'. Returns False if an active company has it.
        """
        sec = self.db.get_securities()
        row = sec[sec['symbol'] == symbol]
        if row.empty:
            return True
        delisted = row['delist_date'].iloc[0]
        if pd.isna(delisted):
            return False
        moved = f"{symbol}~{pd.Timestamp(delisted).year}"
        self.db.rename_symbol(symbol, moved)
        rename_in_live_files(symbol, moved)
        return True

    def refresh_companies(self, dry_run=False) -> dict:
        from scripts.load_universe import build_master
        from data.tiingo import to_db_symbol

        securities = self.db.get_securities()
        known = securities.dropna(subset=['perma_ticker']).set_index('perma_ticker')['symbol'].to_dict()
        master = build_master(self.tiingo, HISTORY_START)
        stats = {'new': [], 'renamed': []}

        for r in master[master['is_active']].itertuples():
            wanted = to_db_symbol(r.ticker)
            if r.perma_ticker in known:
                old = known[r.perma_ticker]
                if old == wanted or '~' in old:
                    continue
                stats['renamed'].append((old, wanted))
                if not dry_run and self._make_room(wanted):
                    self.db.rename_symbol(old, wanted)
                    rename_in_live_files(old, wanted)
                    known[r.perma_ticker] = wanted
                continue

            stats['new'].append(wanted)
            if dry_run:
                continue
            if not self._make_room(wanted):
                logger.warning("%s: symbol held by another active company - skipping new listing %s",
                               wanted, r.perma_ticker)
                continue
            bars = self.tiingo.prices(r.perma_ticker, start=HISTORY_START)
            if bars.empty:
                continue
            self.db.insert_ohlcv_data(wanted, bars, replace=True)
            self.db.upsert_securities(pd.DataFrame([{
                'symbol': wanted, 'name': r.name, 'type': 'CS', 'exchange': r.exchange,
                'list_date': bars['timestamp'].min(), 'perma_ticker': r.perma_ticker}]))
            known[r.perma_ticker] = wanted
        logger.info("Company list: %d new, %d renamed %s", len(stats['new']), len(stats['renamed']),
                    stats['renamed'][:10])
        return stats

    # ------------------------------------------------------------- prices
    def update_prices(self, target: pd.Timestamp, dry_run=False) -> dict:
        securities = self.db.get_securities()
        active = securities[securities['delist_date'].isna() & securities['perma_ticker'].notna()]
        last = self.db.symbol_ranges().set_index('symbol')['last']
        recent = self.db.get_bars(target - pd.Timedelta(days=OVERLAP_DAYS + 7), target,
                                  symbols=active['symbol'].tolist(), columns=('close',))
        stored = {s: g.set_index('timestamp')['close'] for s, g in recent.groupby('symbol')}

        todo = active[active['symbol'].map(last) < target]
        stats = {'checked': len(todo), 'appended': 0, 'reloaded': 0, 'no_new_bar': 0, 'failed': []}
        logger.info("Prices: %d active securities, %d behind %s", len(active), len(todo), target.date())
        if dry_run:
            return stats

        for i, r in enumerate(todo.itertuples(), 1):
            start = last[r.symbol] - pd.Timedelta(days=OVERLAP_DAYS)
            try:
                bars = self.tiingo.prices(r.perma_ticker if r.symbol != 'SPY' else 'SPY', start=start, end=target)
            except Exception:
                logger.exception("%s: price download failed", r.symbol)
                stats['failed'].append(r.symbol)
                continue
            new = bars[bars['timestamp'] > last[r.symbol]]
            if new.empty:
                stats['no_new_bar'] += 1
                continue
            old = stored.get(r.symbol, pd.Series(dtype=float))
            overlap = bars.set_index('timestamp')['close'].reindex(old.index).dropna()
            revised = len(overlap) and ((overlap - old[overlap.index]).abs() > 1e-6 * old[overlap.index].abs()).any()
            corporate_action = (new['div_cash'] > 0).any() or (new['split_factor'] != 1).any()
            if revised or corporate_action:
                full = self.tiingo.prices(r.perma_ticker if r.symbol != 'SPY' else 'SPY', start=HISTORY_START)
                self.db.insert_ohlcv_data(r.symbol, full, replace=True)
                stats['reloaded'] += 1
            else:
                self.db.insert_bars(new.assign(symbol=r.symbol))
                stats['appended'] += 1
            if i % 500 == 0:
                logger.info("Prices: %d/%d (%d reloaded)", i, len(todo), stats['reloaded'])
        return stats

    # ------------------------------------------------------- fundamentals
    def update_fundamentals(self, today: pd.Timestamp, new_symbols=(), dry_run=False) -> dict:
        from data.sec_edgar import parse_company_facts, periodic_filers_on
        from scripts.load_universe import link_ciks

        if new_symbols and not dry_run:
            link_ciks(self.db, self.sec, symbols=list(new_symbols))
        links = self.db.get_security_ciks()
        by_cik = links.groupby('cik')['symbol'].apply(list).to_dict()

        state = json.loads(EDGAR_STATE_FILE.read_text()) if EDGAR_STATE_FILE.exists() else {}
        since = pd.Timestamp(state.get('last_index_date', today - pd.Timedelta(days=7)))
        filers = set()
        for day in pd.date_range(since + pd.Timedelta(days=1), today):
            filers |= periodic_filers_on(self.sec, day)
        new_ciks = set(links.loc[links['symbol'].isin(new_symbols), 'cik'])
        refresh = (filers & set(by_cik)) | new_ciks
        logger.info("Fundamentals: %d periodic filers since %s, %d tracked to refresh",
                    len(filers), since.date(), len(refresh))
        if dry_run:
            return {'refreshed': 0, 'to_refresh': len(refresh)}

        rows_added = 0
        for cik in sorted(refresh):
            facts = self.sec.company_facts(cik)
            if not facts:
                continue
            for symbol in by_cik.get(cik, []):
                rows_added += self.db.insert_fundamentals(parse_company_facts(facts, symbol))
        EDGAR_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        EDGAR_STATE_FILE.write_text(json.dumps({'last_index_date': f"{today:%Y-%m-%d}"}))
        return {'refreshed': len(refresh), 'rows_added': rows_added}

    # ---------------------------------------------------------------- run
    def run(self, now: datetime = None, dry_run=False) -> int:
        from scripts.load_universe import set_listing_dates

        target = last_completed_session_candidate(now)
        logger.info("Target session: %s", target.date())
        companies = self.refresh_companies(dry_run)
        prices = self.update_prices(target, dry_run)
        logger.info("Prices: %s", {k: (len(v) if isinstance(v, list) else v) for k, v in prices.items()})
        if dry_run:
            return 0

        spy_last = self.db.latest_timestamp('SPY')
        if spy_last is None or spy_last < target:
            logger.error("SPY has no bar for %s (latest %s). Market holiday, or Tiingo has not "
                         "published the session yet - rerun later.", target.date(), spy_last)
            if spy_last is not None and (target - spy_last).days > 4:
                return 1
            logger.info("Treating %s as a market holiday (SPY current to %s)", target.date(), spy_last.date())
        else:
            ranges = self.db.symbol_ranges().set_index('symbol')['last']
            sec = self.db.get_securities()
            active = sec[sec['delist_date'].isna() & (sec['type'] != 'ETF')]['symbol']
            current = (active.map(ranges) >= spy_last).mean()
            if current < MIN_UPDATED_FRACTION:
                logger.error("Only %.0f%% of active stocks have a bar for %s - update looks incomplete",
                             100 * current, spy_last.date())
                return 1

        set_listing_dates(self.db)
        if self.sec is not None:
            funds = self.update_fundamentals(pd.Timestamp(datetime.now(MARKET_TZ).date()), companies['new'])
            logger.info("Fundamentals: %s", funds)
        import config
        if config.SCREEN_NAME == 'leaders':
            from scripts.build_factor_history import update_history
            update_history(self.db)   # adds the new quarter / completed 12-month returns
        return 0


def main():
    parser = argparse.ArgumentParser(description='Update prices, company list and fundamentals')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be fetched')
    parser.add_argument('--skip-fundamentals', action='store_true')
    args = parser.parse_args()

    setup_logging('daily_update')
    from data.database import Database
    from data.sec_edgar import SecClient
    from data.tiingo import TiingoClient
    try:
        db = Database()
        db.create_tables()
        updater = TiingoDailyUpdater(db, TiingoClient(), None if args.skip_fundamentals else SecClient())
        return updater.run(dry_run=args.dry_run)
    except Exception:
        logger.exception("Daily update FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
