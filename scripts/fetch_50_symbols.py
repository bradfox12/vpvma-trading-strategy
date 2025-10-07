import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.api_client import MarketDataAPI
from data.database import Database
from datetime import datetime, timedelta
import time

print("="*70)
print("FETCHING TOP 50 STOCKS FOR VPVMA TESTING")
print("="*70)

# Top 50 stocks (curated for liquidity and diversity)
symbols = [
    # Mega Cap Tech
    'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'AVGO', 'ORCL', 
    'AMD', 'CRM', 'ADBE', 'NFLX', 'INTC', 'QCOM',
    
    # Large Cap Growth
    'V', 'MA', 'HD', 'DIS', 'NKE', 'PFE', 'ABBV', 'UNH', 'JNJ', 'PG', 
    'KO', 'PEP', 'WMT', 'COST', 'MCD',
    
    # Financials/Industrials
    'JPM', 'BAC', 'GS', 'MS', 'C', 'BA', 'CAT', 'GE', 'RTX', 'LMT',
    
    # High-Volatility Tech
    'SHOP', 'SQ', 'COIN', 'PLTR', 'SNAP', 'UBER', 'LYFT', 'ABNB', 'RBLX', 'ZM',
    
    # Index ETFs
    'SPY', 'QQQ', 'IWM', 'DIA'
]

print(f"\nSymbols to fetch: {len(symbols)}")
print(f"Symbols: {', '.join(symbols)}")

# Date range: Maximum available (5 years back)
end_date = datetime.now()
start_date = datetime(2020, 1, 1)  # Go back to 2020

print(f"\nDate range: {start_date.date()} to {end_date.date()}")
print(f"Expected: ~1,200-1,300 trading days per symbol")
print(f"\n⚠️  This will take ~15-20 minutes (rate limits)")
print("="*70)

api = MarketDataAPI(provider='polygon')
db = Database(db_type='postgresql')

# Check which symbols already exist
existing_symbols = db.list_symbols()
new_symbols = [s for s in symbols if s not in existing_symbols]
update_symbols = [s for s in symbols if s in existing_symbols]

print(f"\nNew symbols to fetch: {len(new_symbols)}")
print(f"Existing symbols to update: {len(update_symbols)}")

if new_symbols:
    print(f"\nNew: {', '.join(new_symbols)}")
if update_symbols:
    print(f"\nUpdating: {', '.join(update_symbols)}")

proceed = input(f"\nProceed with fetching {len(symbols)} symbols? (y/n): ")
if proceed.lower() != 'y':
    print("Cancelled.")
    exit(0)

print("\n" + "="*70)
print("STARTING DATA FETCH")
print("="*70)

successful = []
failed = []

for i, symbol in enumerate(symbols, 1):
    print(f"\n[{i}/{len(symbols)}] {symbol}", end=' ')
    print("-" * 50)
    
    try:
        # Fetch from Polygon
        print(f"  Fetching from {start_date.date()}...", end=' ')
        
        df = api.fetch_ohlcv(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            interval='1d'
        )
        
        if len(df) == 0:
            print("✗ No data returned")
            failed.append((symbol, "No data"))
            continue
        
        actual_start = df['timestamp'].min()
        actual_end = df['timestamp'].max()
        years_of_data = (actual_end - actual_start).days / 365.25
        
        print(f"✓ {len(df)} records")
        print(f"  Range: {actual_start.date()} to {actual_end.date()} ({years_of_data:.1f} years)")
        
        # Store in database
        print(f"  Storing...", end=' ')
        db.insert_ohlcv_data(symbol, df, replace=True)
        print("✓")
        
        successful.append({
            'symbol': symbol,
            'records': len(df),
            'years': years_of_data
        })
        
        # Rate limiting (Starter plan: 100 requests/min = ~0.6 sec per request)
        # Use 12 sec to be safe
        if i < len(symbols):
            wait_time = 12
            print(f"  Waiting {wait_time}s...", end='', flush=True)
            time.sleep(wait_time)
            print(" ✓")
        
    except Exception as e:
        print(f"✗ Error: {e}")
        failed.append((symbol, str(e)))
        
        # If rate limited, wait longer
        if "429" in str(e):
            print("  Rate limit hit. Waiting 60 seconds...")
            time.sleep(60)

# Summary
print("\n" + "="*70)
print("FETCH SUMMARY")
print("="*70)

if successful:
    print(f"\n✓ Successfully fetched: {len(successful)}/{len(symbols)}")
    
    total_records = sum(s['records'] for s in successful)
    avg_years = sum(s['years'] for s in successful) / len(successful)
    
    print(f"\n  Total records: {total_records:,}")
    print(f"  Avg years per symbol: {avg_years:.1f}")
    
    print(f"\n  Symbols: {', '.join([s['symbol'] for s in successful])}")

if failed:
    print(f"\n✗ Failed: {len(failed)}")
    for symbol, error in failed:
        print(f"  {symbol}: {error}")

print(f"\n{'='*70}")
print(f"Total symbols in database: {len(db.list_symbols())}")
print("\n✓ Data fetch complete!")
print("\nNext: Run 'python scripts/batch_backtest_50.py' to test all symbols")
print("="*70)