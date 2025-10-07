import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.database import Database
from main import calculate_vpvma_indicator
import pandas as pd
import numpy as np

print("="*60)
print("INVESTIGATING VPVMA ANOMALY")
print("="*60)

symbol = input("\nEnter symbol (default: SPY): ").upper() or 'SPY'

db = Database(db_type='postgresql')
df = db.get_ohlcv_data(symbol)
open_p, high, low, close, volume = db.get_ohlcv_arrays(symbol)

# Calculate VPVMA
result = calculate_vpvma_indicator(high, low, close, open_p, volume)

df['vpvma'] = result['vpvma']
df['vpvmas'] = result['vpvmas']
df_valid = df[35:].copy()

# Find extreme values
print(f"\n📊 VPVMA Statistics for {symbol}:")
print(f"{'='*60}")
print(f"Mean:   {df_valid['vpvma'].mean():.2f}")
print(f"Median: {df_valid['vpvma'].median():.2f}")
print(f"Std:    {df_valid['vpvma'].std():.2f}")
print(f"Min:    {df_valid['vpvma'].min():.2f}")
print(f"Max:    {df_valid['vpvma'].max():.2f}")

# Find top 10 extreme values
print(f"\n🔍 TOP 10 HIGHEST VPVMA VALUES:")
print(f"{'='*60}")
extremes = df_valid.nlargest(10, 'vpvma')[['timestamp', 'open', 'high', 'low', 'close', 'volume', 'vpvma', 'vpvmas']]
print(extremes.to_string(index=False))

# Check for data quality issues around extremes
print(f"\n🔍 DATA QUALITY CHECK:")
print(f"{'='*60}")

for idx, row in extremes.head(3).iterrows():
    date = row['timestamp']
    print(f"\n{date.date()}:")
    
    # Get surrounding data
    idx_loc = df_valid.index.get_loc(idx)
    context = df_valid.iloc[max(0, idx_loc-2):min(len(df_valid), idx_loc+3)]
    
    print(context[['timestamp', 'close', 'volume', 'vpvma']].to_string(index=False))
    
    # Check for anomalies
    if row['volume'] == 0:
        print("  ⚠️ ZERO VOLUME - This could cause calculation issues!")
    
    if row['high'] == row['low']:
        print("  ⚠️ No price movement (High = Low)")
    
    # Check for extreme volume changes
    if idx_loc > 0:
        prev_vol = df_valid.iloc[idx_loc-1]['volume']
        vol_change = abs(row['volume'] - prev_vol) / prev_vol if prev_vol > 0 else 0
        if vol_change > 10:
            print(f"  ⚠️ Volume spike: {vol_change*100:.1f}% change from previous day")

# Check April 2025 specifically
april_2025 = df_valid[(df_valid['timestamp'] >= '2025-04-01') & (df_valid['timestamp'] <= '2025-04-30')]

if not april_2025.empty:
    print(f"\n{'='*60}")
    print("APRIL 2025 DETAILED ANALYSIS:")
    print(f"{'='*60}")
    
    april_max = april_2025['vpvma'].max()
    april_date = april_2025[april_2025['vpvma'] == april_max]['timestamp'].iloc[0]
    
    print(f"\nMax VPVMA in April: {april_max:.2f} on {april_date.date()}")
    print(f"\nFull April data:")
    print(april_2025[['timestamp', 'close', 'volume', 'vpvma', 'vpvmas']].to_string(index=False))

# Look for calculation issues
print(f"\n{'='*60}")
print("POTENTIAL ISSUES:")
print(f"{'='*60}")

issues = []

# Check for zero volume
zero_vol = (df_valid['volume'] == 0).sum()
if zero_vol > 0:
    issues.append(f"❌ {zero_vol} days with zero volume")
    zero_vol_dates = df_valid[df_valid['volume'] == 0]['timestamp'].head()
    print(f"\nZero volume dates: {[d.date() for d in zero_vol_dates]}")

# Check for NaN values
nan_count = df_valid['vpvma'].isna().sum()
if nan_count > 0:
    issues.append(f"❌ {nan_count} NaN values in VPVMA")

# Check for infinite values
inf_count = np.isinf(df_valid['vpvma']).sum()
if inf_count > 0:
    issues.append(f"❌ {inf_count} infinite values in VPVMA")

# Check for extreme outliers (>3 standard deviations)
mean = df_valid['vpvma'].mean()
std = df_valid['vpvma'].std()
outliers = df_valid[abs(df_valid['vpvma'] - mean) > 3 * std]
if len(outliers) > 0:
    issues.append(f"⚠️ {len(outliers)} outliers (>3 std deviations)")
    print(f"\nOutlier dates:")
    print(outliers[['timestamp', 'vpvma']].to_string(index=False))

if not issues:
    print("\n✓ No obvious data quality issues detected")
    print("\nThe April spike may be legitimate due to:")
    print("  • Extreme market volatility")
    print("  • Banking crisis / market event")
    print("  • Unusual volume pattern")
else:
    print("\nIssues found:")
    for issue in issues:
        print(f"  {issue}")

print(f"\n{'='*60}")
print("RECOMMENDATION:")
print(f"{'='*60}")

if april_max > 1000:
    print("\n⚠️ The April 2025 spike is extreme (>1000)")
    print("\nNext steps:")
    print("  1. Check if there was a market event in April 2025")
    print("  2. Verify SPY data quality for that period")
    print("  3. Consider capping extreme VPVMA values")
    print("  4. Test indicator on other symbols (AAPL, MSFT)")
else:
    print("\n✓ VPVMA values are within reasonable range")
    print("✓ Ready to proceed with backtesting")