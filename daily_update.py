"""
Daily Data Update Script - Fixed for Weekends
==============================================
Run after market close to update database with latest OHLCV data
Automatically handles weekends and holidays

Usage:
    python daily_update.py
    
Schedule with Windows Task Scheduler:
    Time: 4:30 PM ET (Mon-Fri)
    Action: python C:\\bkf\\daily_update.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from data.database import Database
import requests
from time import sleep
import logging

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed, will use system environment variables

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('daily_update.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class DailyDataUpdater:
    """
    Fetches and updates daily OHLCV data for entire universe
    Handles weekends and holidays automatically
    """
    
    def __init__(self, api_key=None):
        """
        Initialize updater
        
        Args:
            api_key: Polygon.io API key (or set POLYGON_API_KEY env variable)
        """
        self.db = Database(db_type='postgresql')
        
        # Get API key from environment or parameter
        import os
        self.api_key = api_key or os.getenv('MARKET_API_KEY') or os.getenv('POLYGON_API_KEY')
        
        if not self.api_key:
            logger.warning("No API key found. Set MARKET_API_KEY or POLYGON_API_KEY environment variable.")
        
        self.base_url = "https://api.polygon.io/v2/aggs/ticker"
    
    def get_last_trading_day(self):
        """
        Get the most recent trading day (handles weekends/holidays)
        
        Returns:
            datetime: Last trading day
        """
        today = datetime.now()
        current_day = today.weekday()
        current_hour = today.hour
        
        # If it's after 4:30 PM ET on a weekday, we can use today
        if current_day < 5 and current_hour >= 16:  # Weekday after 4 PM
            logger.info(f"After market close on {today.strftime('%A')} - using today's data")
            return today
        
        # Otherwise, we need the previous trading day
        if current_day == 0:  # Monday
            target = today - timedelta(days=3)  # Friday
            logger.info(f"It's Monday - using Friday's data ({target.date()})")
        elif current_day == 6:  # Sunday
            target = today - timedelta(days=2)  # Friday
            logger.info(f"It's Sunday - using Friday's data ({target.date()})")
        elif current_day == 5:  # Saturday
            target = today - timedelta(days=1)  # Friday
            logger.info(f"It's Saturday - using Friday's data ({target.date()})")
        else:  # Tuesday-Friday before market close
            target = today - timedelta(days=1)
            logger.info(f"Before market close - using yesterday's data ({target.date()})")
        
        return target
    
    def verify_market_was_open(self, date):
        """
        Verify if market was open on a given date by checking SPY
        
        Args:
            date: Date to verify
            
        Returns:
            bool: True if market was open
        """
        date_str = date.strftime('%Y-%m-%d')
        url = f"{self.base_url}/SPY/range/1/day/{date_str}/{date_str}"
        
        params = {
            'apiKey': self.api_key,
            'adjusted': 'true'
        }
        
        try:
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                return 'results' in data and len(data['results']) > 0
        except:
            pass
        
        return False
    
    def get_last_valid_trading_day(self):
        """
        Get the last valid trading day, checking if market was actually open
        
        Returns:
            datetime: Last confirmed trading day
        """
        target = self.get_last_trading_day()
        
        # Verify market was open
        attempts = 0
        while attempts < 5:
            logger.info(f"Checking if market was open on {target.date()}...")
            
            if self.verify_market_was_open(target):
                logger.info("[OK] Confirmed: Market was open on {target.date()}")
                return target
            else:
                logger.info(f"Market was closed on {target.date()} (holiday?), trying previous day...")
                target = target - timedelta(days=1)
                # Skip to Friday if we hit a weekend
                while target.weekday() >= 5:
                    target = target - timedelta(days=1)
                attempts += 1
        
        # Fallback - just use what we calculated
        return self.get_last_trading_day()
        
    def fetch_daily_bar(self, symbol, date=None):
        """
        Fetch single day's OHLCV data from Polygon.io
        
        Args:
            symbol: Stock ticker
            date: Date to fetch (defaults to last trading day)
        
        Returns:
            dict with OHLCV data or None if error
        """
        if date is None:
            date = self.get_last_valid_trading_day()
        
        date_str = date.strftime('%Y-%m-%d')
        
        # Polygon API endpoint
        url = f"{self.base_url}/{symbol}/range/1/day/{date_str}/{date_str}"
        
        params = {
            'apiKey': self.api_key,
            'adjusted': 'true'
        }
        
        try:
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                if 'results' in data and len(data['results']) > 0:
                    bar = data['results'][0]
                    
                    return {
                        'symbol': symbol,
                        'timestamp': pd.to_datetime(bar['t'], unit='ms'),
                        'open': bar['o'],
                        'high': bar['h'],
                        'low': bar['l'],
                        'close': bar['c'],
                        'volume': bar['v']
                    }
                else:
                    logger.debug(f"{symbol}: No data returned for {date_str}")
                    return None
                    
            elif response.status_code == 429:
                logger.warning(f"{symbol}: Rate limit hit, waiting 60s...")
                sleep(60)
                return self.fetch_daily_bar(symbol, date)  # Retry
                
            else:
                logger.error(f"{symbol}: API error {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"{symbol}: Error fetching data - {e}")
            return None
    
    def update_symbol(self, symbol, date=None):
        """
        Update single symbol with latest data
        
        Args:
            symbol: Stock ticker
            date: Date to update (defaults to last trading day)
        
        Returns:
            bool: True if successful
        """
        if date is None:
            date = self.get_last_valid_trading_day()
            
        bar = self.fetch_daily_bar(symbol, date)
        
        if bar is None:
            return False
        
        try:
            # Check if data already exists
            existing = self.db.get_ohlcv_data(
                symbol,
                start_date=bar['timestamp'],
                end_date=bar['timestamp']
            )
            
            if len(existing) > 0:
                logger.debug(f"{symbol}: Data already exists for {bar['timestamp'].date()}")
                return True
            
            # Insert new data
            df = pd.DataFrame([bar])
            self.db.insert_ohlcv_data(symbol, df, replace=False)
            
            logger.info(f"{symbol}: [OK] Updated {bar['timestamp'].date()} - Close: ${bar['close']:.2f}")
            return True
            
        except Exception as e:
            logger.error(f"{symbol}: Database error - {e}")
            return False
    
    def update_universe(self, date=None):
        """
        Update entire universe with latest data
        
        Args:
            date: Date to update (defaults to last trading day)
        
        Returns:
            dict with update statistics
        """
        logger.info("="*80)
        logger.info("DAILY DATA UPDATE - WEEKEND AWARE")
        logger.info("="*80)
        logger.info(f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S (%A)')}")
        
        if date is None:
            date = self.get_last_valid_trading_day()
        
        logger.info(f"Target date: {date.strftime('%Y-%m-%d (%A)')}")
        logger.info(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Get universe from database
        symbols = self.db.list_symbols()
        logger.info(f"Universe size: {len(symbols)} symbols")
        
        # Check if we already have data for this date
        logger.info("\nChecking if update needed...")
        sample_df = self.db.get_ohlcv_data(
            'SPY',
            start_date=date,
            end_date=date
        )
        
        if len(sample_df) > 0:
            logger.info("[OK] Database already has data for target date")
            logger.info("  No update needed - data is current")
            return {
                'date': date,
                'total': len(symbols),
                'successful': len(symbols),
                'failed': 0,
                'success_rate': 100,
                'already_current': True
            }
        
        # Update each symbol
        successful = 0
        failed = 0
        already_exists = 0
        
        logger.info("\nUpdating symbols...")
        for idx, symbol in enumerate(symbols, 1):
            if idx % 10 == 0:
                logger.info(f"Progress: [{idx}/{len(symbols)}] {idx/len(symbols)*100:.1f}%")
            
            result = self.update_symbol(symbol, date)
            
            if result:
                successful += 1
            else:
                failed += 1
            
            # Rate limiting: 5 calls per second max for free tier
            if idx % 5 == 0:
                sleep(1.2)
        
        # Summary
        logger.info("\n" + "="*80)
        logger.info("UPDATE COMPLETE")
        logger.info("="*80)
        logger.info(f"Date: {date.strftime('%Y-%m-%d (%A)')}")
        logger.info(f"Successful: {successful}/{len(symbols)}")
        logger.info(f"Failed: {failed}/{len(symbols)}")
        logger.info(f"Success rate: {successful/len(symbols)*100:.1f}%")
        logger.info(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("="*80)
        
        return {
            'date': date,
            'total': len(symbols),
            'successful': successful,
            'failed': failed,
            'success_rate': successful/len(symbols)*100
        }
    
    def verify_update(self, date=None):
        """
        Verify that update was successful by checking data quality
        
        Args:
            date: Date to verify
        
        Returns:
            dict with verification results
        """
        if date is None:
            date = self.get_last_valid_trading_day()
        
        logger.info("\n" + "="*80)
        logger.info("VERIFICATION")
        logger.info("="*80)
        
        symbols = self.db.list_symbols()
        issues = []
        
        for symbol in symbols[:10]:  # Check first 10 symbols
            try:
                df = self.db.get_ohlcv_data(
                    symbol,
                    start_date=date - timedelta(days=5),
                    end_date=date
                )
                
                if len(df) == 0:
                    issues.append(f"{symbol}: No data found")
                elif df['timestamp'].max() < pd.Timestamp(date):
                    issues.append(f"{symbol}: Latest data is {df['timestamp'].max().date()}")
                    
            except Exception as e:
                issues.append(f"{symbol}: Error - {e}")
        
        if len(issues) == 0:
            logger.info("[OK] Verification passed - data looks good!")
        else:
            logger.warning(f"Found {len(issues)} potential issues:")
            for issue in issues:
                logger.warning(f"  - {issue}")
        
        return {
            'issues_found': len(issues),
            'issues': issues
        }


def main():
    """
    Main execution function
    """
    updater = DailyDataUpdater()
    
    # Update with last trading day's data
    results = updater.update_universe()
    
    # Only verify if we actually updated
    if not results.get('already_current', False):
        verification = updater.verify_update()
    
    # Return exit code (0 = success, 1 = issues)
    if results['success_rate'] > 95 or results.get('already_current', False):
        logger.info("\n[SUCCESS] Daily update completed successfully!")
        return 0
    else:
        logger.warning("\n[WARNING] Daily update completed with issues")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)