"""
Tiingo: US stock list (active + delisted) and fully adjusted daily prices

- supported_tickers.zip (public, updated daily): ticker, exchange, assetType,
  priceCurrency, startDate, endDate. Delisted listings have an endDate in the past.
  The same ticker can appear several times when it was reused by a different
  company (e.g. AAC); each listing period is a separate security.
- /tiingo/daily/<ticker>/prices: adjOpen/adjHigh/adjLow/adjClose/adjVolume are
  adjusted for splits AND dividends, matching the database convention.
- /tiingo/daily/<ticker>: metadata incl. company name (used to match delisted
  tickers to SEC CIKs).

API key: TIINGO_API_KEY in .env. Free plan: 50 requests/hour, 500 symbols/month.
Power plan: 10,000 requests/hour, 100,000/day.
"""

import io
import logging
import os
import re
import time
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

SUPPORTED_TICKERS_URL = 'https://apimedia.tiingo.com/docs/tiingo/daily/supported_tickers.zip'
API_URL = 'https://api.tiingo.com/tiingo/daily'

US_EXCHANGES = {'NYSE', 'NASDAQ', 'NYSE MKT', 'AMEX', 'NYSE ARCA', 'BATS'}
# Tickers that are not common shares: preferreds (-P-, -P), units, warrants, rights
NON_COMMON = re.compile(r'(?:-P-|-P[A-Z]?$|-U$|-UN$|-WS|-WT|-W$|-R$|-RT$|\.U$|\.W$)')


def to_db_symbol(ticker: str) -> str:
    """Tiingo class-share format (BRK-B) -> database format (BRK.B)"""
    return ticker.upper().replace('-', '.')


def to_tiingo_ticker(symbol: str) -> str:
    return symbol.upper().replace('.', '-')


class TiingoClient:
    """Small Tiingo REST client with rate-limit back-off"""

    def __init__(self, api_key: Optional[str] = None, session=None, sleep=time.sleep):
        self.api_key = api_key or os.getenv('TIINGO_API_KEY')
        if not self.api_key:
            raise ValueError("TIINGO_API_KEY is not set - add it to .env")
        self.session = session or requests.Session()
        self.sleep = sleep

    def _get(self, url: str, params: dict = None):
        headers = {'Authorization': f'Token {self.api_key}', 'Content-Type': 'application/json'}
        for attempt in range(1, 5):
            response = self.session.get(url, params=params or {}, headers=headers, timeout=60)
            if response.status_code == 429:
                wait = 60 * attempt
                logger.warning("Tiingo rate limit - waiting %ds", wait)
                self.sleep(wait)
                continue
            if response.status_code == 404:
                return None
            if response.status_code != 200:
                raise RuntimeError(f"Tiingo {url} -> HTTP {response.status_code}: {response.text[:200]}")
            return response
        raise RuntimeError(f"Tiingo still rate limiting: {url}")

    def meta(self, symbol: str) -> Optional[dict]:
        response = self._get(f"{API_URL}/{to_tiingo_ticker(symbol)}")
        return None if response is None else response.json()

    def prices(self, symbol: str, start='2008-01-01', end=None) -> pd.DataFrame:
        """
        Fully adjusted daily bars [timestamp, open, high, low, close, volume, div_cash, split_factor]
        (empty if Tiingo has no data)
        """
        params = {'startDate': str(pd.Timestamp(start).date()), 'format': 'csv'}
        if end is not None:
            params['endDate'] = str(pd.Timestamp(end).date())
        response = self._get(f"{API_URL}/{to_tiingo_ticker(symbol)}/prices", params)
        if response is None or not response.text.strip() or response.text.lstrip().startswith(('{', '[')):
            return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume',
                                         'div_cash', 'split_factor'])
        return parse_prices_csv(response.text)


def parse_prices_csv(text: str) -> pd.DataFrame:
    raw = pd.read_csv(io.StringIO(text))
    df = pd.DataFrame({
        'timestamp': pd.to_datetime(raw['date']).dt.tz_localize(None).dt.normalize(),
        'open': raw['adjOpen'].astype(float),
        'high': raw['adjHigh'].astype(float),
        'low': raw['adjLow'].astype(float),
        'close': raw['adjClose'].astype(float),
        'volume': raw['adjVolume'].astype(float),
        'div_cash': raw.get('divCash', 0.0),
        'split_factor': raw.get('splitFactor', 1.0),
    })
    return df.dropna(subset=['open', 'high', 'low', 'close']).reset_index(drop=True)


def load_supported_tickers(session=None) -> pd.DataFrame:
    """Tiingo's full listing table (no API key needed)"""
    response = (session or requests).get(SUPPORTED_TICKERS_URL, timeout=120)
    response.raise_for_status()
    df = pd.read_csv(io.BytesIO(response.content), compression='zip')
    df['startDate'] = pd.to_datetime(df['startDate'])
    df['endDate'] = pd.to_datetime(df['endDate'])
    return df


def us_stock_listings(listings: pd.DataFrame, active_since='2008-01-01',
                      always_include=('SPY',)) -> pd.DataFrame:
    """
    US exchange-listed stocks (USD) that traded on or after `active_since`,
    excluding preferreds, units, warrants and rights. `always_include` adds
    non-stock symbols the system needs (SPY: calendar and market regime).

    Returns:
        DataFrame [symbol, ticker, exchange, start, end, reused] where `reused`
        marks tickers that belonged to more than one listing.
    """
    df = listings[(listings['assetType'] == 'Stock') & (listings['priceCurrency'] == 'USD')
                  & listings['exchange'].isin(US_EXCHANGES)
                  & (listings['endDate'] >= pd.Timestamp(active_since))].copy()
    df = df[df['ticker'].notna() & ~df['ticker'].str.upper().str.contains(NON_COMMON)]
    extra = listings[listings['ticker'].isin(always_include) & (listings['priceCurrency'] == 'USD')]
    df = pd.concat([df, extra]).drop_duplicates(['ticker', 'startDate'])
    df['symbol'] = df['ticker'].map(to_db_symbol)
    df['reused'] = df.duplicated('symbol', keep=False)
    return df.rename(columns={'startDate': 'start', 'endDate': 'end'})[
        ['symbol', 'ticker', 'exchange', 'start', 'end', 'reused']].reset_index(drop=True)


def load_company_master(client: 'TiingoClient') -> pd.DataFrame:
    """
    Every company Tiingo covers (active and inactive), one row per permaTicker:
    [perma_ticker, ticker, name, is_active, is_adr]. Reused tickers appear once
    per company, so older companies can be loaded by perma_ticker.
    """
    response = client._get('https://api.tiingo.com/tiingo/fundamentals/meta', {'format': 'csv'})
    df = pd.read_csv(io.StringIO(response.text))
    return pd.DataFrame({
        'perma_ticker': df['permaTicker'].str.upper(),
        'ticker': df['ticker'].str.upper(),
        'name': df['name'],
        'is_active': df['isActive'].astype(bool),
        'is_adr': df['isADR'].astype(bool),
    }).dropna(subset=['perma_ticker', 'ticker']).drop_duplicates('perma_ticker').reset_index(drop=True)
