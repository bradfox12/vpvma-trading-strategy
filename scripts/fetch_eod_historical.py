"""
Fetch 20 years of historical data from EOD Historical Data
Based on working fetch_and_store.py pattern - SECURE VERSION
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.database import Database
from datetime import datetime
import time
import requests
import pandas as pd
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

print("="*80)
print("FETCHING 20 YEARS OF HISTORICAL DATA - EOD HISTORICAL")
print("EOD Historical Data All-World Essential ($19.99/mo)")
print("="*80)

# Configuration - API key from environment
EOD_API_KEY = os.getenv('EOD_API_KEY')

if not EOD_API_KEY:
    print("\n❌ ERROR: EOD_API_KEY not found!")
    print("\nPlease add your API key to the .env file:")
    print('  echo "EOD_API_KEY=your_key_here" >> .env')
    print("\nOr export it temporarily:")
    print('  export EOD_API_KEY="your_key_here"')
    sys.exit(1)

# Your symbols
symbols = [
    'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA',
    'NFLX', 'AMD', 'INTC', 'QCOM', 'AVGO', 'ORCL', 'CRM',
    'SHOP', 'UBER', 'LYFT', 'COIN', 'RBLX', 'PLTR', 'ABNB',
    'SNAP', 'SQ', 'ZM', 'ADBE', 'NOW', 'DDOG', 'SNOW',
    'DIS', 'BA', 'CAT', 'GE', 'UNH', 'JPM', 'BAC', 'MS',
    'C', 'GS', 'MA', 'V', 'COST', 'HD', 'NKE', 'MCD',
    'WMT', 'PG', 'KO', 'PEP', 'JNJ', 'PFE', 'ABBV', 'LMT',
    'RTX', 'HON', 'UPS', 'FDX',
    'SPY', 'QQQ'
]

# 20 years of history!
end_date = datetime.now()
start_date = datetime(2005, 1, 1)

print(f"\nFetching from: {start_date.date()} to {end_date.date()}")
print(f"Symbols: {len(symbols)} stocks")
print(f"EOD Historical provides full history back to 2000+")
print("="*80)

# Initialize database
db = Database(db_type='postgresql')

def fetch_eod_historical(symbol, api_key, start_date, end_date):
    """Fetch data from EOD Historical API"""
    url = f"https://eodhistoricaldata.com/api/eod/{symbol}.US"
    
    params = {
        'api_token': api_key,
        'from': start_date.strftime('%Y-%m-%d'),
        'to': end_date.strftime('%Y-%m-%d'),
        'period': 'd',
        'fmt': 'json'
    }
    
    response = requests.get(url, params=params, timeout=30)
    
    if response.status_code != 200:
        raise Exception(f"API error: {response.status_code}")
    
    data = response.json()
    
    if not data:
        return pd.DataFrame()
    
    # Convert to DataFrame - avoid duplicate column names
    raw_df = pd.DataFrame(data)
    
    # Build clean DataFrame with proper columns
    df = pd.DataFrame({
        'timestamp': pd.to_datetime(raw_df['date']),
        'open': raw_df['open'],
        'high': raw_df['high'],
        'low': raw_df['low'],
        'close': raw_df['adjusted_close'],  # Use adjusted for splits/dividends
        'volume': raw_df['volume']
    })
    
    return df

successful = []
failed = []
data_summary = {}

for i, symbol in enumerate(symbols, 1):
    print(f"\n[{i}/{len(symbols)}] {symbol}", end=' ')
    print("-" * 40)
    
    try:
        print(f"  Requesting data from {start_date.date()}...", end=' ')
        
        df = fetch_eod_historical(symbol, EOD_API_KEY, start_date, end_date)
        
        if len(df) == 0:
            print("✗ No data returned")
            failed.append(symbol)
            continue
        
        # Calculate actual date range
        actual_start = df['timestamp'].min()
        actual_end = df['timestamp'].max()
        years_of_data = (actual_end - actual_start).days / 365.25
        
        print(f"✓ Got {len(df)} records")
        print(f"  Actual range: {actual_start.date()} to {actual_end.date()}")
        print(f"  Years of data: {years_of_data:.1f}")
        
        # Store in PostgreSQL using your Database class (replace=True deletes old data)
        print(f"  Storing in database...", end=' ')
        db.insert_ohlcv_data(symbol, df, replace=True)
        print("✓")
        
        successful.append(symbol)
        data_summary[symbol] = {
            'records': len(df),
            'start': actual_start,
            'end': actual_end,
            'years': years_of_data
        }
        
        # Rate limiting - be polite to EOD API
        if i < len(symbols):
            wait_time = 1
            time.sleep(wait_time)
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user!")
        print(f"Progress: {len(successful)}/{len(symbols)} symbols completed")
        break
        
    except Exception as e:
        print(f"✗ Error: {e}")
        failed.append(symbol)
        
        # If rate limited, wait longer
        if "429" in str(e) or "Too Many Requests" in str(e):
            print("  Rate limit hit. Waiting 10 seconds...")
            time.sleep(10)

# Detailed Summary
print("\n" + "="*80)
print("DETAILED SUMMARY")
print("="*80)

if successful:
    print(f"\n✓ Successfully fetched {len(successful)} symbols:\n")
    
    for symbol in successful:
        info = data_summary[symbol]
        print(f"  {symbol:6} | {info['records']:4} records | "
              f"{info['start'].date()} to {info['end'].date()} | "
              f"{info['years']:.1f} years")
    
    # Calculate totals
    total_records = sum(info['records'] for info in data_summary.values())
    avg_years = sum(info['years'] for info in data_summary.values()) / len(successful)
    
    print(f"\n  TOTALS: {total_records:,} records | Avg: {avg_years:.1f} years per symbol")

if failed:
    print(f"\n✗ Failed: {', '.join(failed)}")

print(f"\n{'='*80}")
print(f"Symbols in database: {db.list_symbols()}")
print("\n🎉 20-year historical data fetch complete!")

print(f"\n⚠️  REMINDER: Cancel EOD subscription in 25 days!")
print(f"📅 Set reminder for: {(pd.Timestamp.now() + pd.Timedelta(days=25)).strftime('%Y-%m-%d')}")

print("\n" + "="*80)
print("NEXT STEPS:")
print("="*80)
print("1. Verify data quality:")
print("   python scripts/verify_historical_data.py")
print("\n2. Run 20-year dynamic backtest:")
print("   python scripts/run_dynamic_backtest.py")
print("="*80)