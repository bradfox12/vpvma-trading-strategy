"""
Market data API client
Fetches OHLCV data from various market data providers
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional
from secure_config import SecureConfig


class MarketDataAPI:
    """
    Generic market data API client
    Supports multiple providers (customize based on your API)
    """
    
    def __init__(self, provider: str = 'generic'):
        """
        Initialize API client
        
        Args:
            provider: API provider ('alpha_vantage', 'polygon', 'finnhub', 'generic')
        """
        self.provider = provider
        self.api_key = SecureConfig.MARKET_API_KEY
        
        # Set base URL based on provider
        self.base_urls = {
            'alpha_vantage': 'https://www.alphavantage.co/query',
            'polygon': 'https://api.polygon.io',
            'finnhub': 'https://finnhub.io/api/v1',
            'generic': ''  # Set your API base URL here
        }
        
        self.base_url = self.base_urls.get(provider, '')
    
    def fetch_ohlcv(
        self,
        symbol: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        interval: str = '1d'
    ) -> pd.DataFrame:
        """
        Fetch OHLCV data from API
        
        Args:
            symbol: Stock/crypto symbol
            start_date: Start date for data
            end_date: End date for data
            interval: Time interval ('1m', '5m', '1h', '1d', etc.)
        
        Returns:
            DataFrame with columns [timestamp, open, high, low, close, volume]
        """
        if self.provider == 'alpha_vantage':
            return self._fetch_alpha_vantage(symbol, interval)
        elif self.provider == 'polygon':
            return self._fetch_polygon(symbol, start_date, end_date, interval)
        elif self.provider == 'finnhub':
            return self._fetch_finnhub(symbol, start_date, end_date, interval)
        else:
            return self._fetch_generic(symbol, start_date, end_date, interval)
    
    def _fetch_alpha_vantage(self, symbol: str, interval: str) -> pd.DataFrame:
        """Fetch from Alpha Vantage API"""
        function_map = {
            '1d': 'TIME_SERIES_DAILY',
            '1h': 'TIME_SERIES_INTRADAY',
            '5m': 'TIME_SERIES_INTRADAY'
        }
        
        params = {
            'function': function_map.get(interval, 'TIME_SERIES_DAILY'),
            'symbol': symbol,
            'apikey': self.api_key,
            'outputsize': 'full'
        }
        
        if interval in ['1h', '5m']:
            params['interval'] = interval
        
        response = requests.get(self.base_url, params=params)
        data = response.json()
        
        # Parse Alpha Vantage response (customize based on actual response structure)
        # This is a simplified example
        time_series_key = [k for k in data.keys() if 'Time Series' in k][0]
        df = pd.DataFrame.from_dict(data[time_series_key], orient='index')
        
        # Rename columns and convert types
        df = df.rename(columns={
            '1. open': 'open',
            '2. high': 'high',
            '3. low': 'low',
            '4. close': 'close',
            '5. volume': 'volume'
        })
        
        df.index = pd.to_datetime(df.index)
        df = df.reset_index().rename(columns={'index': 'timestamp'})
        df = df.astype({
            'open': float,
            'high': float,
            'low': float,
            'close': float,
            'volume': int
        })
        
        return df.sort_values('timestamp').reset_index(drop=True)
    
    def _fetch_polygon(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        interval: str
    ) -> pd.DataFrame:
        """Fetch from Polygon.io API"""
        # Implement Polygon API logic
        # See: https://polygon.io/docs/stocks/get_v2_aggs_ticker__stocksticker__range__multiplier___timespan___from___to
        
        url = f"{self.base_url}/v2/aggs/ticker/{symbol}/range/1/day/{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}"
        
        params = {'apiKey': self.api_key}
        response = requests.get(url, params=params)
        data = response.json()
        
        # Parse response
        results = data.get('results', [])
        df = pd.DataFrame(results)
        
        # Rename columns
        df = df.rename(columns={
            't': 'timestamp',
            'o': 'open',
            'h': 'high',
            'l': 'low',
            'c': 'close',
            'v': 'volume'
        })
        
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        
        return df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
    
    def _fetch_finnhub(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        interval: str
    ) -> pd.DataFrame:
        """Fetch from Finnhub API"""
        # Implement Finnhub API logic
        pass
    
    def _fetch_generic(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        interval: str
    ) -> pd.DataFrame:
        """
        Generic API fetch - customize this for your specific API
        
        Replace this with your actual API implementation
        """
        # Example structure - modify for your API
        url = f"{self.base_url}/ohlcv"
        
        params = {
            'symbol': symbol,
            'start': start_date.isoformat() if start_date else None,
            'end': end_date.isoformat() if end_date else None,
            'interval': interval,
            'api_key': self.api_key
        }
        
        response = requests.get(url, params=params)
        
        if response.status_code != 200:
            raise Exception(f"API request failed: {response.status_code} - {response.text}")
        
        data = response.json()
        
        # Convert to DataFrame - modify based on your API response format
        df = pd.DataFrame(data['data'])  # Adjust based on actual response structure
        
        # Ensure required columns exist
        required_columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        df = df[required_columns]
        
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        return df.sort_values('timestamp').reset_index(drop=True)


# Example usage
if __name__ == "__main__":
    # Initialize API client
    api = MarketDataAPI(provider='polygon')  # or 'alpha_vantage', 'finnhub'
    
    # Fetch data
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365)
    
    df = api.fetch_ohlcv(
        symbol='AAPL',
        start_date=start_date,
        end_date=end_date,
        interval='1d'
    )
    
    print(f"Fetched {len(df)} records")
    print(df.head())