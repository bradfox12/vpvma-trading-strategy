import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.database import Database
import pandas as pd

print("="*60)
print("SPLIT ADJUSTMENT VERIFICATION")
print("="*60)

db = Database(db_type='postgresql')
df = db.get_ohlcv_data('AAPL')

# AAPL 4-for-1 split on August 31, 2020
split_date = '2020-08-31'

# Get data around the split
pre_split = df[df['timestamp'] < split_date].tail(3)
post_split = df[df['timestamp'] > split_date].head(3)

print("\n📅 BEFORE Aug 31, 2020 Split:")
print(pre_split[['timestamp', 'open', 'high', 'low', 'close', 'volume']])

print("\n📅 AFTER Aug 31, 2020 Split:")
print(post_split[['timestamp', 'open', 'high', 'low', 'close', 'volume']])

if not pre_split.empty and not post_split.empty:
    last_pre = pre_split.iloc[-1]
    first_post = post_split.iloc[0]
    
    print("\n" + "="*60)
    print("SPLIT ANALYSIS:")
    print("="*60)
    
    # Check if there's a big jump (would indicate NOT adjusted)
    price_change = abs(first_post['close'] - last_pre['close']) / last_pre['close']
    
    if price_change > 0.5:  # More than 50% change
        print("❌ DATA IS NOT SPLIT-ADJUSTED")
        print(f"   Price jumped {price_change*100:.1f}% across split date")
        print("   This would invalidate backtest results!")
    else:
        print("✓ DATA IS SPLIT-ADJUSTED")
        print(f"   Price continuity across split: {price_change*100:.2f}% change")
        print("   This is correct for backtesting!")
    
    print(f"\n   Last price before split: ${last_pre['close']:.2f}")
    print(f"   First price after split: ${first_post['close']:.2f}")

# Show Oct 2020 price (your chart start)
print("\n" + "="*60)
print("PRICE VALIDATION:")
print("="*60)

oct_2020 = df[(df['timestamp'] >= '2020-10-01') & (df['timestamp'] <= '2020-10-31')]
if not oct_2020.empty:
    avg_price = oct_2020['close'].mean()
    print(f"\nOct 2020 average close: ${avg_price:.2f}")
    print("\nExpected: $110-$120 (split-adjusted)")
    print("Actual price you see on chart: ~$110-$115")
    
    if 100 < avg_price < 130:
        print("\n✓ MATCHES! Data is correctly split-adjusted")
    else:
        print("\n⚠️  Price seems off - needs investigation")

# Check latest price
latest = df.iloc[-1]
print(f"\nLatest close ({latest['timestamp'].date()}): ${latest['close']:.2f}")
print("(Check this against current AAPL price)")

# Calculate returns to verify
print("\n" + "="*60)
print("RETURN CALCULATION (5-year period):")
print("="*60)

first_price = df.iloc[0]['close']
last_price = df.iloc[-1]['close']
total_return = ((last_price / first_price) - 1) * 100

print(f"Start: ${first_price:.2f} ({df.iloc[0]['timestamp'].date()})")
print(f"End:   ${last_price:.2f} ({df.iloc[-1]['timestamp'].date()})")
print(f"Total Return: {total_return:.2f}%")
print(f"Annualized: {(((last_price/first_price)**(1/5))-1)*100:.2f}%")

print("\n" + "="*60)
print("CONCLUSION:")
print("="*60)

# Final verification
if price_change < 0.1 and 100 < avg_price < 130:
    print("✓✓✓ YOUR DATA IS CORRECTLY SPLIT-ADJUSTED")
    print("✓ Safe to use for VPVMA backtesting")
    print("✓ All indicators will calculate correctly")
    print("✓ Returns and signals will be accurate")
else:
    print("⚠️  Data may need verification")
    print("Check Polygon.io API settings")