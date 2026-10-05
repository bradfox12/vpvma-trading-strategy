"""
Phase 2: full load of US stocks (Tiingo prices + SEC EDGAR fundamentals)

Stages (each resumable - rerunning skips work already done):
  master        Tiingo company list (active + inactive) -> candidate securities:
                not ADRs, ticker listed on a major US exchange since --start
  prices        Adjusted daily bars by Tiingo permaTicker (so older companies
                behind reused tickers load correctly); sets listing dates
  ciks          Link each security to its SEC CIK: SEC ticker map for active
                stocks, company name + filing dates for delisted ones
  fundamentals  SEC company facts (bulk companyfacts.zip, or the API for small
                runs) -> point-in-time quarterly rows, incl. predecessors and
                data/cik_overrides.csv
  report        Coverage report in logs/

Usage:
    python scripts/load_universe.py                     # everything
    python scripts/load_universe.py --stages prices ciks
    python scripts/load_universe.py --limit 50          # quick test on 50 companies
    python scripts/load_universe.py --refresh-prices    # re-download prices too

Needs TIINGO_API_KEY (Power plan for the full run) and SEC_USER_AGENT in .env.
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
from data.sec_edgar import (CACHE_DIR, COMPANYFACTS_ZIP_URL, SecClient, current_ticker_map,
                            filed_periodic_reports_between, find_predecessors, iter_companyfacts_zip,
                            load_cik_lookup, load_cik_overrides, match_cik_by_name, parse_company_facts)
from data.tiingo import (TiingoClient, US_EXCHANGES, NON_COMMON, load_company_master,
                         load_supported_tickers, to_db_symbol)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = PROJECT_ROOT / 'logs'
STAGES = ['master', 'prices', 'ciks', 'fundamentals', 'report']
API_FACTS_LIMIT = 300   # below this many CIKs use the API instead of the 1.4 GB bulk file
# All SEC filers had to file XBRL financials by mid-2011; a CIK whose data starts
# well after that (or after the stock listed) may have a predecessor CIK
XBRL_FULL_ADOPTION = pd.Timestamp('2011-06-15')

logger = logging.getLogger('load_universe')


# ---------------------------------------------------------------- master

def build_master(tiingo: TiingoClient, start: str, limit: int = None) -> pd.DataFrame:
    """
    Candidate securities [symbol, ticker, perma_ticker, name, is_active, exchange].
    Older companies whose ticker was later reused get symbol 'TICKER~YEAR'.
    """
    master = load_company_master(tiingo)
    listings = load_supported_tickers()
    us = listings[listings['exchange'].isin(US_EXCHANGES) & (listings['endDate'] >= pd.Timestamp(start))
                  & (listings['assetType'] == 'Stock') & (listings['priceCurrency'] == 'USD')]
    us = us.assign(ticker=us['ticker'].str.upper())
    exchange = us.sort_values('endDate').drop_duplicates('ticker', keep='last').set_index('ticker')['exchange']

    not_shares = master['name'].fillna('').str.contains(r'\b(?:Units?|Rights?|Warrants?)\b', case=False)
    df = master[~master['is_adr'] & master['ticker'].isin(exchange.index)
                & ~master['ticker'].str.contains(NON_COMMON) & ~not_shares].copy()
    df['exchange'] = df['ticker'].map(exchange)
    # active company keeps the plain symbol; inactive ones sharing a ticker get suffixed later
    df = df.sort_values(['ticker', 'is_active'], ascending=[True, False])
    df['symbol'] = df['ticker'].map(to_db_symbol)
    df['reused'] = df.duplicated('ticker', keep='first')
    if limit:
        keep = df[df['ticker'].isin(['SPY'])]
        df = pd.concat([keep, df.drop(keep.index).sample(n=min(limit, len(df)), random_state=1)])
    logger.info("Master: %d companies (%d active, %d inactive, %d older owners of reused tickers)",
                len(df), df['is_active'].sum(), (~df['is_active']).sum(), df['reused'].sum())
    return df.reset_index(drop=True)


def spy_row(tiingo: TiingoClient) -> dict:
    meta = tiingo.meta('SPY') or {}
    return {'symbol': 'SPY', 'ticker': 'SPY', 'perma_ticker': 'SPY', 'name': meta.get('name', 'SPDR S&P 500'),
            'is_active': True, 'exchange': 'NYSE ARCA', 'reused': False, 'type': 'ETF'}


# ---------------------------------------------------------------- prices

def load_prices(db: Database, tiingo: TiingoClient, master: pd.DataFrame, start: str, refresh: bool):
    """
    Download bars per company (by permaTicker) and save its securities row
    immediately, so an interrupted run resumes where it stopped.
    """
    existing = db.get_securities()
    done = set(existing['perma_ticker'].dropna()) if not refresh and len(existing) else set()
    todo = master[~master['perma_ticker'].isin(done)]
    logger.info("Prices: %d companies to download (%d already loaded)", len(todo), len(master) - len(todo))

    for i, r in enumerate(todo.itertuples(), 1):
        try:
            bars = tiingo.prices(r.perma_ticker, start=start)
        except Exception:
            logger.exception("%s (%s): price download failed - will retry on the next run", r.ticker, r.perma_ticker)
            continue
        if bars.empty:
            continue
        symbol = r.symbol if not r.reused else f"{r.symbol}~{bars['timestamp'].max().year}"
        db.insert_ohlcv_data(symbol, bars, replace=True)
        db.upsert_securities(pd.DataFrame([{'symbol': symbol, 'name': r.name, 'type': r.type,
                                            'exchange': r.exchange, 'list_date': bars['timestamp'].min(),
                                            'perma_ticker': r.perma_ticker}]))
        if i % 250 == 0:
            logger.info("Prices: %d/%d companies", i, len(todo))
    set_listing_dates(db)


def set_listing_dates(db: Database):
    """list_date = first bar; delist_date = last bar if it ended >10 days before the latest SPY bar"""
    sec = db.get_securities()
    if sec.empty:
        return
    ranges = db.symbol_ranges().set_index('symbol')
    latest = db.latest_timestamp('SPY') or ranges['last'].max()
    sec['list_date'] = sec['symbol'].map(ranges['first'])
    last = sec['symbol'].map(ranges['last'])
    sec['delist_date'] = last.where(last < latest - pd.Timedelta(days=10))
    db.upsert_securities(sec.dropna(subset=['list_date']))
    logger.info("Securities: %d (%d delisted)", len(sec), sec['delist_date'].notna().sum())


# ------------------------------------------------------------------ ciks

def link_ciks(db: Database, sec_client: SecClient, symbols=None):
    securities = db.get_securities()
    securities = securities[securities['type'] != 'ETF']
    if symbols is not None:
        securities = securities[securities['symbol'].isin(symbols)]
    current = current_ticker_map(sec_client).set_index('symbol')['cik']
    lookup = load_cik_lookup(sec_client)
    linked = set(db.get_security_ciks()['symbol'])
    stats = {'ticker_map': 0, 'name': 0, 'unmatched': 0}

    for i, r in enumerate(securities.itertuples(), 1):
        if r.symbol in linked:
            continue
        cik, how = None, None
        if pd.isna(r.delist_date) and r.symbol in current.index:
            cik, how = int(current[r.symbol]), 'SEC ticker map'
            stats['ticker_map'] += 1
        else:
            end = r.delist_date if pd.notna(r.delist_date) else pd.Timestamp.now()
            best = (0, 0)
            try:
                for candidate in match_cik_by_name(r.name, lookup)[:25]:
                    n = filed_periodic_reports_between(sec_client.submissions(candidate) or {}, r.list_date, end)
                    best = max(best, (n, candidate))
            except Exception:
                logger.exception("%s: CIK name match failed - skipped", r.symbol)
            if best[0] > 0:
                cik, how = int(best[1]), f'name match "{r.name}" ({best[0]} reports)'
                stats['name'] += 1
        if cik is None:
            stats['unmatched'] += 1
            continue
        db.set_security_ciks(r.symbol, [(cik, how)])
        if i % 250 == 0:
            logger.info("CIK links: %d/%d (%s)", i, len(securities), stats)
    logger.info("CIK links done: %s", stats)


# ---------------------------------------------------------- fundamentals

def iter_facts(sec_client: SecClient, ciks):
    ciks = sorted(set(int(c) for c in ciks))
    if len(ciks) < API_FACTS_LIMIT:
        for cik in ciks:
            yield cik, sec_client.company_facts(cik)
        return
    path = CACHE_DIR / 'companyfacts.zip'
    if not path.exists() or (pd.Timestamp.now() - pd.Timestamp(path.stat().st_mtime, unit='s')).days >= 1:
        logger.info("Downloading SEC companyfacts.zip (~1.4 GB)...")
        sec_client.download(COMPANYFACTS_ZIP_URL, path)
    yield from iter_companyfacts_zip(path, ciks)


def first_filed(facts) -> pd.Timestamp:
    filed = [x['filed'] for tax in (facts or {}).get('facts', {}).values()
             for concept in tax.values() for unit in concept['units'].values() for x in unit]
    return pd.Timestamp(min(filed)) if filed else pd.Timestamp.now()


def load_fundamentals(db: Database, sec_client: SecClient, start: str, only_missing: bool = False):
    securities = db.get_securities().set_index('symbol')
    links = db.get_security_ciks()
    if only_missing:
        have = set(db.get_fundamentals('2100-01-01', fields=['revenue', 'net_income'])['symbol'])
        links = links[~links['symbol'].isin(have)]
        logger.info("Fundamentals: %d linked symbols without data", links['symbol'].nunique())
    overrides = load_cik_overrides()
    lookup = None

    # 1. add predecessor + override CIKs
    by_cik = links.groupby('cik')['symbol'].apply(list).to_dict()
    for cik, facts in iter_facts(sec_client, by_cik):
        for symbol in by_cik[cik]:
            extra = []
            needed = max(pd.Timestamp(securities.at[symbol, 'list_date']), pd.Timestamp(start),
                         XBRL_FULL_ADOPTION)
            if first_filed(facts) > needed + pd.Timedelta(days=365):
                lookup = lookup if lookup is not None else load_cik_lookup(sec_client)
                extra = [(c, 'predecessor') for c in find_predecessors(sec_client, cik, first_filed(facts),
                                                                      needed, lookup)]
            extra += [(c, 'override') for c in overrides.get(symbol, []) if c != cik]
            if extra:
                how = links.loc[links['symbol'] == symbol, 'how'].iloc[0]
                db.set_security_ciks(symbol, [(cik, how)] + extra)

    # 2. parse every linked CIK and store under its symbol(s)
    all_links = db.get_security_ciks()
    links = all_links[all_links['symbol'].isin(set(links['symbol']))]
    by_cik = links.groupby('cik')['symbol'].apply(list).to_dict()
    done = 0
    for cik, facts in iter_facts(sec_client, by_cik):
        if not facts:
            continue
        for symbol in by_cik[cik]:
            rows = parse_company_facts(facts, symbol)
            if not rows.empty:
                db.insert_fundamentals(rows)
        done += 1
        if done % 250 == 0:
            logger.info("Fundamentals: %d/%d filers", done, len(by_cik))
    logger.info("Fundamentals loaded for %d filers", done)


# ---------------------------------------------------------------- report

def coverage_report(db: Database, min_avg_volume: float = 250_000):
    """
    How much of the tradeable market has fundamentals. A stock counts as
    tradeable in a year if its average daily share volume that year was at least
    `min_avg_volume`; it counts as covered if revenue (or, for banks, net
    interest income) was reported in the ~6 months before mid-year.
    """
    securities = db.get_securities()
    stocks = securities[securities['type'] != 'ETF']
    links = db.get_security_ciks()
    revenue = db.get_fundamentals('2100-01-01', fields=['revenue', 'net_interest_income'])
    avg_volume = db.avg_volume_by_year()

    rows = []
    for year in range(2009, pd.Timestamp.now().year + 1):
        mid = pd.Timestamp(f'{year}-06-30')
        listed = stocks[(stocks['list_date'] <= mid) & (stocks['delist_date'].isna() | (stocks['delist_date'] >= mid))]
        vol = listed['symbol'].map(lambda s: avg_volume.get((s, year), 0))
        liquid = listed[vol >= min_avg_volume]
        recent = revenue[(revenue['available_date'] <= mid) & (revenue['period_end'] >= mid - pd.Timedelta(days=200))]
        covered = liquid['symbol'].isin(set(recent['symbol']))
        rows.append({'year': year, 'listed_stocks': len(listed), 'tradeable_by_volume': len(liquid),
                     'tradeable_with_fundamentals': int(covered.sum()),
                     'coverage_pct': round(100 * covered.mean(), 1) if len(liquid) else None})
    by_year = pd.DataFrame(rows)

    liquid_ever = set(avg_volume[avg_volume >= min_avg_volume].index.get_level_values('symbol'))
    unmatched = stocks[~stocks['symbol'].isin(set(links['symbol']))]
    no_revenue = stocks[stocks['symbol'].isin(set(links['symbol'])) & ~stocks['symbol'].isin(set(revenue['symbol']))]
    REPORT_DIR.mkdir(exist_ok=True)
    by_year.to_csv(REPORT_DIR / 'coverage_by_year.csv', index=False)
    cols = ['symbol', 'name', 'exchange', 'list_date', 'delist_date']
    for frame, name in ((unmatched, 'coverage_unmatched_cik.csv'), (no_revenue, 'coverage_no_revenue.csv')):
        frame.assign(ever_tradeable=frame['symbol'].isin(liquid_ever))[cols + ['ever_tradeable']] \
            .sort_values('ever_tradeable', ascending=False).to_csv(REPORT_DIR / name, index=False)

    logger.info("Securities: %d stocks (%d active), %d linked to SEC, %d unmatched (%d ever tradeable), "
                "%d linked without revenue (%d ever tradeable)",
                len(stocks), stocks['delist_date'].isna().sum(), stocks['symbol'].isin(set(links['symbol'])).sum(),
                len(unmatched), unmatched['symbol'].isin(liquid_ever).sum(),
                len(no_revenue), no_revenue['symbol'].isin(liquid_ever).sum())
    logger.info("Coverage by year (tradeable = avg volume >= %s shares/day):\n%s",
                f"{min_avg_volume:,.0f}", by_year.to_string(index=False))
    logger.info("Details: %s", REPORT_DIR)


def main():
    parser = argparse.ArgumentParser(description='Full load of US stocks: Tiingo prices + SEC fundamentals')
    parser.add_argument('--stages', nargs='*', default=STAGES, choices=STAGES)
    parser.add_argument('--start', default='2008-01-01')
    parser.add_argument('--limit', type=int, help='Random sample of N companies (testing)')
    parser.add_argument('--refresh-prices', action='store_true')
    parser.add_argument('--db-url', help='Override the database (default from .env)')
    parser.add_argument('--only-missing', action='store_true',
                        help='fundamentals stage: only symbols that have no fundamentals yet')
    args = parser.parse_args()

    setup_logging('load_universe')
    db = Database(url=args.db_url) if args.db_url else Database()
    db.create_tables()
    tiingo = TiingoClient()
    sec_client = SecClient()

    if 'master' in args.stages or 'prices' in args.stages:
        master = build_master(tiingo, args.start, args.limit)
        master = pd.concat([pd.DataFrame([spy_row(tiingo)]), master[master['symbol'] != 'SPY']],
                           ignore_index=True)
        master['type'] = master['type'].fillna('CS') if 'type' in master else 'CS'
        if 'prices' in args.stages:
            load_prices(db, tiingo, master, args.start, args.refresh_prices)
    if 'ciks' in args.stages:
        link_ciks(db, sec_client)
    if 'fundamentals' in args.stages:
        load_fundamentals(db, sec_client, args.start, only_missing=args.only_missing)
    if 'report' in args.stages:
        coverage_report(db)
    return 0


if __name__ == '__main__':
    sys.exit(main())
