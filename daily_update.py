"""
Daily Data Update
=================
Brings the database up to date with the latest completed trading session.

- Backfills EVERY session missed since the last stored SPY bar (not just today)
- One grouped-daily request per session covers all tickers
- Market holidays are detected from the data (an empty session is skipped),
  so no hand-maintained holiday calendar is needed
- Splits and dividends on each session are applied to stored history BEFORE the
  new bar is inserted, keeping the series fully adjusted like the historical load
- Bars are stored at the session date (midnight)

Data source: Massive (formerly Polygon.io) REST API, MARKET_API_KEY in .env.
Works on the free plan (5 requests/minute; ~3 requests per session).

Usage:
    python daily_update.py            # update to the last completed session
    python daily_update.py --dry-run  # show which sessions would be fetched
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import argparse
import logging
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from logging_setup import setup_logging

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / '.env')
except ImportError:
    pass

logger = logging.getLogger('daily_update')

MARKET_TZ = ZoneInfo('America/New_York')
SESSION_READY = (16, 30)         # a session's bars are fetched after 16:30 ET
MAX_RETRIES = 5
DEFAULT_BASE_URL = 'https://api.massive.com'
MAX_BACKFILL_SESSIONS = 60       # beyond this, re-run the historical loader instead


class MarketDataClient:
    """Minimal REST client with rate-limit handling"""

    def __init__(self, api_key: str, base_url: str = None, session=None, sleep=time.sleep):
        if not api_key:
            raise ValueError("MARKET_API_KEY is not set - add it to .env")
        self.api_key = api_key
        self.base_url = (base_url or os.getenv('MARKET_API_BASE_URL') or DEFAULT_BASE_URL).rstrip('/')
        self.session = session or requests.Session()
        self.sleep = sleep

    def get(self, path_or_url: str, params: dict = None) -> dict:
        url = path_or_url if path_or_url.startswith('http') else f"{self.base_url}{path_or_url}"
        params = dict(params or {}, apiKey=self.api_key)
        for attempt in range(1, MAX_RETRIES + 1):
            response = self.session.get(url, params=params, timeout=30)
            if response.status_code == 429:
                wait = 15 * attempt
                logger.warning("Rate limited (attempt %d/%d) - waiting %ds", attempt, MAX_RETRIES, wait)
                self.sleep(wait)
                continue
            if response.status_code != 200:
                raise RuntimeError(f"GET {url} -> HTTP {response.status_code}: {response.text[:200]}")
            return response.json()
        raise RuntimeError(f"GET {url} still rate limited after {MAX_RETRIES} attempts")

    def get_all(self, path: str, params: dict) -> list:
        """Follow next_url pagination"""
        data = self.get(path, params)
        results = list(data.get('results') or [])
        while data.get('next_url'):
            data = self.get(data['next_url'])
            results.extend(data.get('results') or [])
        return results

    def grouped_daily(self, date: pd.Timestamp) -> pd.DataFrame:
        """All US stock bars for one session (split-adjusted); empty on holidays"""
        data = self.get(f"/v2/aggs/grouped/locale/us/market/stocks/{date:%Y-%m-%d}", {'adjusted': 'true'})
        bars = pd.DataFrame(data.get('results') or [], columns=['T', 'o', 'h', 'l', 'c', 'v'])
        return bars.rename(columns={'T': 'symbol', 'o': 'open', 'h': 'high', 'l': 'low',
                                    'c': 'close', 'v': 'volume'})

    def splits(self, date: pd.Timestamp) -> list:
        return self.get_all('/stocks/v1/splits', {'execution_date': f"{date:%Y-%m-%d}", 'limit': 5000})

    def dividends(self, date: pd.Timestamp) -> list:
        return self.get_all('/stocks/v1/dividends', {'ex_dividend_date': f"{date:%Y-%m-%d}", 'limit': 5000})


def last_completed_session_candidate(now: datetime = None) -> pd.Timestamp:
    """Latest weekday whose session has closed (holidays are found from the data)"""
    now = (now or datetime.now(MARKET_TZ)).astimezone(MARKET_TZ)
    day = pd.Timestamp(now.date())
    if (now.hour, now.minute) < SESSION_READY:
        day -= pd.Timedelta(days=1)
    while day.weekday() >= 5:
        day -= pd.Timedelta(days=1)
    return day


class DailyDataUpdater:
    """Fetches missing sessions and keeps stored history adjusted"""

    def __init__(self, db, client: MarketDataClient):
        self.db = db
        self.client = client

    def sessions_to_fetch(self, now: datetime = None) -> list:
        last = self.db.latest_timestamp('SPY')
        if last is None:
            raise RuntimeError("No SPY data in the database - run scripts/fetch_eod_historical.py first")
        target = last_completed_session_candidate(now)
        days = list(pd.bdate_range(last.normalize() + pd.Timedelta(days=1), target))
        if len(days) > MAX_BACKFILL_SESSIONS:
            raise RuntimeError(
                f"{len(days)} sessions missing since {last.date()} - re-run the historical loader "
                f"(scripts/fetch_eod_historical.py) instead of backfilling day by day")
        return days

    def apply_corporate_actions(self, date: pd.Timestamp, symbols: set) -> int:
        """Back-adjust stored bars for splits/dividends effective on `date`"""
        applied = 0
        for split in self.client.splits(date):
            symbol = split.get('ticker')
            if symbol not in symbols or not split.get('split_from') or not split.get('split_to'):
                continue
            factor = float(split['split_from']) / float(split['split_to'])
            applied += self.db.apply_adjustment(
                symbol, date, 'split', factor, f"{split['split_to']}-for-{split['split_from']} split")

        dividends = [d for d in self.client.dividends(date)
                     if d.get('ticker') in symbols and d.get('cash_amount')
                     and d.get('currency', 'USD') == 'USD']
        if dividends:
            prev_close = self.db.last_closes_before([d['ticker'] for d in dividends], date)
            for div in dividends:
                symbol, cash = div['ticker'], float(div['cash_amount'])
                close = prev_close.get(symbol)
                if not close or cash >= close:
                    logger.warning("%s: skipping dividend %.4f (previous close %s)", symbol, cash, close)
                    continue
                applied += self.db.apply_adjustment(
                    symbol, date, 'dividend', 1 - cash / close, f"${cash:.4f} cash")
        return applied

    def update(self, now: datetime = None, dry_run: bool = False) -> dict:
        symbols = set(self.db.list_symbols())
        days = self.sessions_to_fetch(now)
        logger.info("Universe: %d symbols | sessions to fetch: %s", len(symbols),
                    ', '.join(f"{d:%Y-%m-%d}" for d in days) or 'none (up to date)')
        stats = {'sessions': 0, 'holidays': 0, 'bars': 0, 'actions': 0, 'missing': {}}
        if dry_run:
            return stats

        for day in days:
            bars = self.client.grouped_daily(day)
            if bars.empty:
                logger.info("%s: no session (market holiday)", day.date())
                stats['holidays'] += 1
                continue
            bars = bars[bars['symbol'].isin(symbols)]
            if 'SPY' not in set(bars['symbol']):
                raise RuntimeError(f"{day.date()}: session data has no SPY bar - aborting to avoid a partial update")

            # Adjust stored history first, then append the (already adjusted) new bars
            stats['actions'] += self.apply_corporate_actions(day, symbols)
            inserted = self.db.insert_bars(bars.assign(timestamp=day))

            missing = sorted(symbols - set(bars['symbol']))
            if missing:
                stats['missing'][f"{day:%Y-%m-%d}"] = missing
                logger.warning("%s: no bar for %d symbols (halted/delisted?): %s",
                               day.date(), len(missing), ', '.join(missing[:20]))
            logger.info("%s: inserted %d bars", day.date(), inserted)
            stats['sessions'] += 1
            stats['bars'] += inserted
        return stats


def main():
    parser = argparse.ArgumentParser(description='Update the database to the last completed session')
    parser.add_argument('--dry-run', action='store_true', help='List sessions to fetch without fetching')
    args = parser.parse_args()

    setup_logging('daily_update')
    from data.database import Database
    try:
        db = Database()
        db.create_tables()
        updater = DailyDataUpdater(db, MarketDataClient(os.getenv('MARKET_API_KEY')))
        stats = updater.update(dry_run=args.dry_run)
    except Exception:
        logger.exception("Daily update FAILED")
        return 1

    logger.info("Update complete: %d sessions, %d holidays, %d bars, %d corporate actions",
                stats['sessions'], stats['holidays'], stats['bars'], stats['actions'])
    return 0


if __name__ == "__main__":
    sys.exit(main())
