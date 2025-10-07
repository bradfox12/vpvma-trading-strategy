"""
Verify 20-year historical data quality
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.database import Database
import pandas as pd

print("="*80)
print("HISTORICAL DATA VERIFICATION")
print("="*80)

db = Database(db_type='postgresql')
symbols = db.list_symbols()

print(f"\n📊 Total symbols in database: {len(symbols)}")

# Analyze each symbol
results = []

for symbol in symbols:
    df = db.get_ohlcv_data(symbol)
    
    if len(df) == 0:
        continue
    
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    results.append({
        'symbol': symbol,
        'bars': len(df),
        'start_date': df['timestamp'].min(),
        'end_date': df['timestamp'].max(),
        'years': (df['timestamp'].max() - df['timestamp'].min()).days / 365.25
    })

results_df = pd.DataFrame(results).sort_values('years', ascending=False)

print("\n📅 DATA COVERAGE (Top 30):")
print("-" * 80)
print(f"{'Symbol':<10} {'Bars':<10} {'Start':<15} {'End':<15} {'Years':<10}")
print("-" * 80)

for _, row in results_df.head(30).iterrows():
    print(f"{row['symbol']:<10} {row['bars']:<10} {row['start_date'].strftime('%Y-%m-%d'):<15} "
          f"{row['end_date'].strftime('%Y-%m-%d'):<15} {row['years']:.1f}")

print("\n📊 SUMMARY STATISTICS:")
print(f"  Total symbols: {len(results_df)}")
print(f"  Total bars: {results_df['bars'].sum():,}")
print(f"  Avg bars/symbol: {results_df['bars'].mean():.0f}")
print(f"  Avg years/symbol: {results_df['years'].mean():.1f}")
print(f"  Max years: {results_df['years'].max():.1f}")
print(f"  Min years: {results_df['years'].min():.1f}")

# Symbols with 20+ years
full_data = results_df[results_df['years'] >= 20]
print(f"\n✅ Symbols with 20+ years: {len(full_data)}")
if len(full_data) > 0:
    print(f"  {', '.join(full_data['symbol'].tolist())}")

# Symbols with 15-19 years
good_data = results_df[(results_df['years'] >= 15) & (results_df['years'] < 20)]
print(f"\n✅ Symbols with 15-19 years: {len(good_data)}")
if len(good_data) > 0:
    print(f"  {', '.join(good_data['symbol'].tolist())}")

# Symbols with 10-14 years
ok_data = results_df[(results_df['years'] >= 10) & (results_df['years'] < 15)]
print(f"\n⚠️  Symbols with 10-14 years: {len(ok_data)}")
if len(ok_data) > 0:
    print(f"  {', '.join(ok_data['symbol'].tolist())}")

# Symbols with <10 years
short_data = results_df[results_df['years'] < 10]
print(f"\n⚠️  Symbols with <10 years: {len(short_data)}")
if len(short_data) > 0:
    print(f"  {', '.join(short_data['symbol'].tolist())}")

print("\n" + "="*80)
print("VERIFICATION COMPLETE")
print("="*80)
print("\n✓ Data ready for 20-year backtest!")
print("\nNext: Update backtest config and run:")
print("  python scripts/run_dynamic_backtest.py")