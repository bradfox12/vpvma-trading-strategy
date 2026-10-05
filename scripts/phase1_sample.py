"""
Phase 1: test SEC EDGAR + Tiingo on a small sample before paying for anything

Loads ~15 stocks (active and delisted) into a separate SQLite database
(data/phase1_sample.db), links each ticker to its SEC CIK, pulls Tiingo prices
and EDGAR fundamentals, and writes a report you can check against the
companies' published results.

Usage:
    python scripts/phase1_sample.py                 # default sample
    python scripts/phase1_sample.py --symbols AAPL TWTR
    python scripts/phase1_sample.py --skip-prices   # EDGAR only (no Tiingo key needed)

Needs SEC_USER_AGENT (and TIINGO_API_KEY unless --skip-prices) in .env.
Uses the Tiingo free plan: ~2 requests per symbol (50/hour limit).
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import logging

import pandas as pd

from logging_setup import setup_logging
import secure_config  # noqa: F401  (loads .env)
from data.database import Database
from data.sec_edgar import (SecClient, current_ticker_map, filed_periodic_reports_between,
                            find_predecessors, load_cik_lookup, load_cik_overrides, match_cik_by_name,
                            parse_company_facts)
from data.tiingo import TiingoClient, load_supported_tickers, us_stock_listings

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / 'data' / 'phase1_sample.db'
REPORT_DIR = PROJECT_ROOT / 'logs'

DEFAULT_SAMPLE = [
    'AAPL', 'MSFT', 'JPM', 'KO', 'NVDA', 'XOM', 'BRK.B', 'GE', 'WMT', 'AMD',   # active
    'TWTR', 'ATVI', 'CELG', 'XLNX', 'LNKD',                                     # delisted
    'SPY',                                                                      # calendar/regime
]
DETAIL_SYMBOLS = ['AAPL', 'JPM', 'TWTR']

logger = logging.getLogger('phase1_sample')


def lookup_table(sec, cache):
    if 'lookup' not in cache:
        cache['lookup'] = load_cik_lookup(sec)
    return cache['lookup']


def resolve_ciks(symbol, listing, current, tiingo, sec, cache, needed_from):
    """([ciks], how, {cik: facts}): the listing's CIK plus predecessor/override CIKs"""
    cik, how = resolve_cik(symbol, listing, current, tiingo, sec, cache)
    if cik is None:
        return [], how, {}
    facts = {cik: sec.company_facts(cik)}
    filed = [x['filed'] for tax in (facts[cik] or {}).get('facts', {}).values()
             for concept in tax.values() for unit in concept['units'].values() for x in unit]
    first_report = min(filed) if filed else pd.Timestamp.now()
    start = max(pd.Timestamp(listing['start']), pd.Timestamp(needed_from))
    extra = find_predecessors(sec, cik, first_report, start, lookup_table(sec, cache))
    if extra:
        how += f" + predecessor {extra}"
    override = [c for c in cache.setdefault('overrides', load_cik_overrides()).get(symbol, [])
                if c != cik and c not in extra]
    if override:
        how += f" + override {override}"
    for c in extra + override:
        facts[c] = sec.company_facts(c)
    return [cik] + extra + override, how, facts


def resolve_cik(symbol, listing, current, tiingo, sec, lookup_cache):
    """(cik, how) for a listing: current SEC map, else company name + filing-date check"""
    if not listing['delisted']:
        hit = current[current['symbol'] == symbol]
        if len(hit):
            return int(hit['cik'].iloc[0]), 'SEC ticker map'
    if tiingo is None:
        return None, 'needs Tiingo name lookup'
    meta = tiingo.meta(symbol) or {}
    name = meta.get('name')
    if not name:
        return None, 'no company name from Tiingo'
    candidates = match_cik_by_name(name, lookup_table(sec, lookup_cache))
    scored = []
    for cik in candidates[:10]:
        sub = sec.submissions(cik) or {}
        scored.append((filed_periodic_reports_between(sub, listing['start'], listing['end']), cik))
    scored = [s for s in scored if s[0] > 0]
    if not scored:
        return None, f'no SEC filer named "{name}" with 10-K/10-Q filings while listed'
    best = max(scored)
    return best[1], f'name match "{name}" ({best[0]} reports while listed)'


def main():
    parser = argparse.ArgumentParser(description='Phase 1 sample test for SEC EDGAR + Tiingo')
    parser.add_argument('--symbols', nargs='*', default=DEFAULT_SAMPLE)
    parser.add_argument('--skip-prices', action='store_true', help='EDGAR only (no Tiingo key needed)')
    parser.add_argument('--start', default='2008-01-01')
    args = parser.parse_args()

    setup_logging('phase1_sample')
    sec = SecClient()
    tiingo = None if args.skip_prices else TiingoClient()

    db = Database(url=f"sqlite:///{DB_PATH}")
    db.create_tables()

    listings = us_stock_listings(load_supported_tickers(), active_since=args.start)
    current = current_ticker_map(sec)
    recent = listings['end'].max() - pd.Timedelta(days=10)
    lookup_cache = {}
    summary = []

    for symbol in args.symbols:
        rows = listings[listings['symbol'] == symbol].sort_values('end')
        if rows.empty:
            logger.warning("%s: not in Tiingo's US stock list", symbol)
            summary.append({'symbol': symbol, 'note': 'not in Tiingo US stock list'})
            continue
        listing = rows.iloc[-1].to_dict()
        listing['delisted'] = listing['end'] < recent
        info = {'symbol': symbol, 'listed': f"{listing['start']:%Y-%m-%d}",
                'delisted': f"{listing['end']:%Y-%m-%d}" if listing['delisted'] else '',
                'reused_ticker': bool(listing['reused'])}

        if tiingo is not None:
            prices = tiingo.prices(symbol, start=args.start)
            if not prices.empty:
                db.insert_ohlcv_data(symbol, prices, replace=True)
                info.update(price_bars=len(prices), first_bar=f"{prices['timestamp'].min():%Y-%m-%d}",
                            last_bar=f"{prices['timestamp'].max():%Y-%m-%d}",
                            splits=int((prices['split_factor'] != 1).sum()),
                            dividends=int((prices['div_cash'] > 0).sum()))

        if symbol != 'SPY':
            ciks, how, all_facts = resolve_ciks(symbol, listing, current, tiingo, sec, lookup_cache, args.start)
            info.update(cik=', '.join(map(str, ciks)) or None, cik_match=how)
            if ciks:
                facts = all_facts[ciks[0]] or {}
                parts = [parse_company_facts(f, symbol) for f in all_facts.values() if f]
                rows_f = (pd.concat(parts).drop_duplicates(['field', 'period_end', 'available_date'])
                          if parts else pd.DataFrame())
                if not rows_f.empty:
                    db.insert_fundamentals(rows_f)
                    rev = rows_f[rows_f['field'] == 'revenue']
                    info.update(sec_name=facts.get('entityName'), fundamental_rows=len(rows_f),
                                revenue_quarters=rev['period_end'].nunique(),
                                first_quarter=f"{rev['period_end'].min():%Y-%m-%d}" if len(rev) else '',
                                last_quarter=f"{rev['period_end'].max():%Y-%m-%d}" if len(rev) else '')
        db.upsert_securities(pd.DataFrame([{
            'symbol': symbol, 'name': info.get('sec_name'), 'type': 'CS' if symbol != 'SPY' else 'ETF',
            'exchange': listing['exchange'], 'list_date': listing['start'],
            'delist_date': listing['end'] if listing['delisted'] else None}]))
        summary.append(info)
        logger.info("%s: %s", symbol, {k: v for k, v in info.items() if k != 'symbol'})

    REPORT_DIR.mkdir(exist_ok=True)
    summary_df = pd.DataFrame(summary)
    summary_df.to_csv(REPORT_DIR / 'phase1_summary.csv', index=False)

    details = []
    for symbol in DETAIL_SYMBOLS:
        f = db.get_fundamentals('2100-01-01', symbols=[symbol])
        if f.empty:
            continue
        first = f.sort_values('available_date').drop_duplicates(['field', 'period_end'])  # as first reported
        p = first.pivot(index='period_end', columns='field', values='value')
        filed = first[first['field'] == 'revenue'].set_index('period_end')['available_date']
        p = p.reindex(columns=['revenue', 'gross_profit', 'operating_income', 'net_income', 'eps_diluted'])
        p['gross_margin'] = p['gross_profit'] / p['revenue']
        p['operating_margin'] = p['operating_income'] / p['revenue']
        p['filed'] = filed
        p = p.dropna(subset=['revenue']).tail(8).reset_index()
        p.insert(0, 'symbol', symbol)
        details.append(p)
    if details:
        detail_df = pd.concat(details)
        detail_df.to_csv(REPORT_DIR / 'phase1_fundamentals_detail.csv', index=False)

    pd.set_option('display.width', 220)
    pd.set_option('display.max_columns', 30)
    print("\n=== SAMPLE SUMMARY ===")
    print(summary_df.to_string(index=False))
    if details:
        print("\n=== LAST 8 QUARTERS AS FIRST REPORTED (check against company press releases) ===")
        print(detail_df.to_string(index=False, float_format=lambda v: f"{v:,.3f}" if abs(v) < 100 else f"{v:,.0f}"))
    print(f"\nReports: {REPORT_DIR / 'phase1_summary.csv'}, {REPORT_DIR / 'phase1_fundamentals_detail.csv'}")
    print(f"Database: {DB_PATH}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
