import sys
from pathlib import Path

# Add parent directory to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Now your imports will work
from data.api_client import MarketDataAPI
from data.database import Database
from datetime import datetime, timedelta
import time

print("="*60)
print("FETCHING MAXIMUM HISTORICAL DATA")
print("Polygon.io Stocks Starter Plan ($29/mo)")
print("="*60)

# Initialize
api = MarketDataAPI(provider='polygon')
db = Database(db_type='postgresql')

# Your symbols
symbols = ['AAPL', 'MSFT', 'GOOGL', 'TSLA', 'AMZN', 'NVDA', 'META', 'SPY']

# Try to get maximum history (test with 10 years, will get what's available)
end_date = datetime.now()
start_date = datetime(2015, 1, 1)  # Go back to 2015 (10 years)

print(f"\nAttempting to fetch from: {start_date.date()} to {end_date.date()}")
print(f"Symbols: {', '.join(symbols)}")
print(f"\nStarter plan typically includes 2+ years of data")
print(f"We'll fetch whatever is available for your plan!")
print("="*60)

successful = []
failed = []
data_summary = {}

for i, symbol in enumerate(symbols, 1):
    print(f"\n[{i}/{len(symbols)}] {symbol}", end=' ')
    print("-" * 40)
    
    try:
        # Fetch from Polygon API (will get max available for your plan)
        print(f"  Requesting data from {start_date.date()}...", end=' ')
        
        df = api.fetch_ohlcv(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            interval='1d'
        )
        
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
        
        # Store in PostgreSQL
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
        
        # Rate limit handling (Starter: 100 requests/minute, so 12 sec buffer is safe)
        if i < len(symbols):
            wait_time = 12
            print(f"  Waiting {wait_time} seconds (rate limit)...", end='', flush=True)
            time.sleep(wait_time)
            print(" ✓")
        
    except Exception as e:
        print(f"✗ Error: {e}")
        failed.append(symbol)
        
        # If rate limited, wait longer
        if "429" in str(e):
            print("  Rate limit hit. Waiting 60 seconds...")
            time.sleep(60)

# Detailed Summary
print("\n" + "="*60)
print("DETAILED SUMMARY")
print("="*60)

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

print(f"\n{'='*60}")
print(f"Symbols in database: {db.list_symbols()}")
print("\n🎉 Historical data fetch complete!")
print("\nNext: Run 'python run_vpvma.py' to calculate signals!")
print(f"{'='*60}")