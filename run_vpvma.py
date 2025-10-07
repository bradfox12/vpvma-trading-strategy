"""
VPVMA Analysis Script
Analyzes trading signals for symbols in the database
"""

from data.database import Database
from main import calculate_vpvma_indicator
import numpy as np
import pandas as pd

print("="*60)
print("VPVMA INDICATOR CALCULATION")
print("="*60)

# Initialize database
db = Database(db_type='postgresql')

# Get available symbols
symbols = db.list_symbols()

if not symbols:
    print("❌ No data in database! Run 'python scripts/fetch_and_store.py' first.")
    exit(1)

print(f"\nAvailable symbols: {', '.join(symbols)}")

# Choose symbol to analyze
symbol = input(f"\nEnter symbol to analyze (default: {symbols[0]}): ").upper() or symbols[0]

if symbol not in symbols:
    print(f"❌ Symbol {symbol} not found in database.")
    exit(1)

print(f"\n{'='*60}")
print(f"ANALYZING: {symbol}")
print(f"{'='*60}")

# Get data info
info = db.get_data_info(symbol)
print(f"\nData Info:")
print(f"  Date Range: {info['start_date']} to {info['end_date']}")
print(f"  Total Records: {info['record_count']}")

# Get OHLCV arrays
open_p, high, low, close, volume = db.get_ohlcv_arrays(symbol)

print(f"\nCalculating VPVMA indicator...")

# Calculate VPVMA
result = calculate_vpvma_indicator(high, low, close, open_p, volume)

# Get the DataFrame for better analysis
df = db.get_ohlcv_data(symbol)
df['vpvma'] = result['vpvma']
df['vpvmas'] = result['vpvmas']
df['signal'] = result['signals']

# Filter out warmup period (first 35 bars have NaN)
df_valid = df[35:].copy()

# Count signals
buy_count = (df_valid['signal'] == 1).sum()
sell_count = (df_valid['signal'] == -1).sum()
total_signals = buy_count + sell_count

print(f"\n{'='*60}")
print("RESULTS")
print(f"{'='*60}")
print(f"Total Trading Signals: {total_signals}")
print(f"  Buy Signals:  {buy_count}")
print(f"  Sell Signals: {sell_count}")

# Show recent signals
print(f"\n{'='*60}")
print("RECENT SIGNALS (Last 20 bars)")
print(f"{'='*60}")

recent = df_valid.tail(20)[['timestamp', 'close', 'vpvma', 'vpvmas', 'signal']].copy()
recent['signal_type'] = recent['signal'].map({1: 'BUY', -1: 'SELL', 0: 'HOLD'})

print(recent.to_string(index=False))

# Find most recent signal
last_signals = df_valid[df_valid['signal'] != 0].tail(5)

if len(last_signals) > 0:
    print(f"\n{'='*60}")
    print("LAST 5 TRADING SIGNALS")
    print(f"{'='*60}")
    
    for idx, row in last_signals.iterrows():
        signal_type = "🟢 BUY" if row['signal'] == 1 else "🔴 SELL"
        print(f"{signal_type}  |  {row['timestamp'].date()}  |  Price: ${row['close']:.2f}")
    
    # Current position
    last_signal = last_signals.iloc[-1]
    if last_signal['signal'] == 1:
        print(f"\n📊 Current Position: LONG (entered at ${last_signal['close']:.2f})")
    else:
        print(f"\n📊 Current Position: SHORT/FLAT (exited at ${last_signal['close']:.2f})")
else:
    print(f"\n💤 No signals in recent data")

# Export to CSV (optional)
export_choice = input(f"\nExport results to CSV? (y/n): ").lower()
if export_choice == 'y':
    filename = f"{symbol}_vpvma_results.csv"
    df_valid.to_csv(filename, index=False)
    print(f"✓ Exported to {filename}")

print(f"\n{'='*60}")
print("🎉 Analysis Complete!")
print(f"{'='*60}")