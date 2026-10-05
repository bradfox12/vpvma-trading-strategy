"""
Load fully adjusted daily history from EOD Historical Data into the database

Each symbol's bars are replaced in one transaction. Open/high/low/close are
all adjusted for splits AND dividends (volume inversely), so every bar is
internally consistent. After this load, daily_update.py keeps the data current
and applies new splits/dividends itself.

Usage:
    python scripts/fetch_eod_historical.py                     # all of symbols.txt from 2005
    python scripts/fetch_eod_historical.py --start 2005-01-01 --symbols AAPL MSFT SPY
    python scripts/fetch_eod_historical.py --missing-only      # resume an interrupted load

Requires EOD_API_KEY in .env (any plan with US end-of-day history).
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import logging
import os
import time

import pandas as pd
import requests

from logging_setup import setup_logging

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SYMBOLS_FILE = PROJECT_ROOT / 'symbols.txt'
FAILED_FILE = PROJECT_ROOT / 'logs' / 'failed_symbols.txt'

logger = logging.getLogger('fetch_eod_historical')


def read_symbols(path: Path) -> list:
    lines = (line.split('#')[0].strip().upper() for line in path.read_text().splitlines())
    return sorted({s for s in lines if s})


def eod_ticker(symbol: str) -> str:
    """Database/Massive format (BRK.B) -> EOD format (BRK-B.US)"""
    return f"{symbol.replace('.', '-')}.US"


def adjust_ohlcv(raw_df: pd.DataFrame) -> pd.DataFrame:
    """
    Fully adjusted OHLCV from EOD's raw prices + adjusted_close.

    Open/high/low are scaled by the same split/dividend factor as the close,
    and volume inversely, so each bar is internally consistent. (Storing the
    adjusted close next to raw open/high/low corrupts typical price and daily
    volatility on every bar before a split or dividend.)
    """
    raw_df = raw_df[raw_df['close'] > 0]
    factor = raw_df['adjusted_close'] / raw_df['close']
    return pd.DataFrame({
        'timestamp': pd.to_datetime(raw_df['date']),
        'open': raw_df['open'] * factor,
        'high': raw_df['high'] * factor,
        'low': raw_df['low'] * factor,
        'close': raw_df['adjusted_close'],
        'volume': (raw_df['volume'] / factor).round().astype('int64'),
    }).reset_index(drop=True)


def fetch_eod_historical(symbol, api_key, start_date, end_date, session=requests) -> pd.DataFrame:
    """Fully adjusted daily bars for one symbol (empty DataFrame if none)"""
    response = session.get(
        f"https://eodhd.com/api/eod/{eod_ticker(symbol)}",
        params={'api_token': api_key, 'from': f"{start_date:%Y-%m-%d}", 'to': f"{end_date:%Y-%m-%d}",
                'period': 'd', 'fmt': 'json'},
        timeout=60,
    )
    if response.status_code == 429:
        raise RuntimeError("rate limited (429)")
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
    data = response.json()
    return adjust_ohlcv(pd.DataFrame(data)) if data else pd.DataFrame()


def main():
    parser = argparse.ArgumentParser(description='Load adjusted daily history from EOD Historical Data')
    parser.add_argument('--symbols', nargs='*', help='Tickers to load (default: symbols.txt)')
    parser.add_argument('--symbols-file', type=Path, default=DEFAULT_SYMBOLS_FILE)
    parser.add_argument('--start', default='2005-01-01')
    parser.add_argument('--missing-only', action='store_true', help='Skip symbols already in the database')
    args = parser.parse_args()

    setup_logging('fetch_eod_historical')
    from data.database import Database

    api_key = os.getenv('EOD_API_KEY')
    if not api_key:
        logger.error("EOD_API_KEY not set - add it to .env")
        return 1

    symbols = sorted({s.upper() for s in args.symbols}) if args.symbols else read_symbols(args.symbols_file)
    if 'SPY' not in symbols:
        symbols.append('SPY')  # required for the trading calendar and market regime

    db = Database()
    db.create_tables()
    if args.missing_only:
        have = set(db.list_symbols())
        symbols = [s for s in symbols if s not in have]

    start, end = pd.Timestamp(args.start), pd.Timestamp.now().normalize()
    logger.info("Loading %d symbols from %s to %s", len(symbols), start.date(), end.date())

    failed = []
    for i, symbol in enumerate(symbols, 1):
        for attempt in range(3):
            try:
                df = fetch_eod_historical(symbol, api_key, start, end)
                break
            except Exception as e:
                logger.warning("[%d/%d] %s: %s (attempt %d)", i, len(symbols), symbol, e, attempt + 1)
                time.sleep(10 * (attempt + 1))
        else:
            failed.append(symbol)
            continue

        if df.empty:
            logger.warning("[%d/%d] %s: no data returned", i, len(symbols), symbol)
            failed.append(symbol)
            continue
        db.insert_ohlcv_data(symbol, df, replace=True)
        logger.info("[%d/%d] %s: %d bars %s to %s", i, len(symbols), symbol, len(df),
                    df['timestamp'].min().date(), df['timestamp'].max().date())
        time.sleep(0.2)

    if failed:
        FAILED_FILE.parent.mkdir(exist_ok=True)
        FAILED_FILE.write_text('\n'.join(failed) + '\n')
        logger.error("%d symbols failed (listed in %s): %s", len(failed), FAILED_FILE, ', '.join(failed))
    logger.info("Done. Next: python scripts/validate_data.py")
    return 1 if 'SPY' in failed else 0


if __name__ == '__main__':
    sys.exit(main())
