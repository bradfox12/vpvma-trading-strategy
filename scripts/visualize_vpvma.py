import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.database import Database
from main import calculate_vpvma_indicator
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import numpy as np

print("="*60)
print("VPVMA SIGNAL VISUALIZATION")
print("="*60)

# Initialize database
db = Database(db_type='postgresql')
symbols = db.list_symbols()

print(f"\nAvailable symbols: {', '.join(symbols)}")
symbol = input(f"\nEnter symbol to visualize (default: AAPL): ").upper() or 'AAPL'

if symbol not in symbols:
    print(f"❌ Symbol {symbol} not found!")
    exit(1)

print(f"\nLoading {symbol} data...")

# Get data
df = db.get_ohlcv_data(symbol)
open_p, high, low, close, volume = db.get_ohlcv_arrays(symbol)

# Calculate VPVMA
result = calculate_vpvma_indicator(high, low, close, open_p, volume)

# Add to dataframe
df['vpvma'] = result['vpvma']
df['vpvmas'] = result['vpvmas']
df['signal'] = result['signals']
df['buy_signal'] = result['buy_signals']
df['sell_signal'] = result['sell_signals']

# Filter out warmup period
df_valid = df[35:].copy()

# Ask for time period
print(f"\nTotal data: {len(df_valid)} days")
print("How much history to display?")
print("  1. Last 3 months")
print("  2. Last 6 months")
print("  3. Last 1 year")
print("  4. Last 2 years")
print("  5. All data (5 years)")

choice = input("\nChoice (default: 3): ") or "3"

periods = {
    "1": 60,
    "2": 120,
    "3": 252,
    "4": 504,
    "5": len(df_valid)
}

lookback = periods.get(choice, 252)
df_plot = df_valid.tail(lookback).copy()

print(f"\nPlotting last {lookback} days...")
print(f"Date range: {df_plot['timestamp'].min().date()} to {df_plot['timestamp'].max().date()}")

# Count signals in view
buy_count = df_plot['buy_signal'].sum()
sell_count = df_plot['sell_signal'].sum()
print(f"Signals in view: {buy_count} buys, {sell_count} sells")

# Create the plot
fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(16, 12), 
                                     gridspec_kw={'height_ratios': [3, 2, 1]})

fig.suptitle(f'{symbol} - VPVMA Indicator Analysis', fontsize=16, fontweight='bold')

# --- SUBPLOT 1: Price with Buy/Sell Signals ---
ax1.plot(df_plot['timestamp'], df_plot['close'], 
         color='blue', linewidth=1.5, label='Close Price', alpha=0.8)

# Mark buy signals
buy_dates = df_plot[df_plot['buy_signal']]['timestamp']
buy_prices = df_plot[df_plot['buy_signal']]['close']
ax1.scatter(buy_dates, buy_prices, color='green', marker='^', 
            s=150, label='Buy Signal', zorder=5, edgecolors='black', linewidths=1.5)

# Mark sell signals
sell_dates = df_plot[df_plot['sell_signal']]['timestamp']
sell_prices = df_plot[df_plot['sell_signal']]['close']
ax1.scatter(sell_dates, sell_prices, color='red', marker='v', 
            s=150, label='Sell Signal', zorder=5, edgecolors='black', linewidths=1.5)

ax1.set_ylabel('Price ($)', fontsize=12, fontweight='bold')
ax1.set_title('Price Chart with Trading Signals', fontsize=12)
ax1.legend(loc='upper left')
ax1.grid(True, alpha=0.3)

# Format x-axis
ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=max(1, lookback//252)))
plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45, ha='right')

# --- SUBPLOT 2: VPVMA and Signal Line ---
ax2.plot(df_plot['timestamp'], df_plot['vpvma'], 
         color='purple', linewidth=2, label='VPVMA Line', alpha=0.9)
ax2.plot(df_plot['timestamp'], df_plot['vpvmas'], 
         color='orange', linewidth=2, label='Signal Line (VPVMAS)', alpha=0.9, linestyle='--')

# Add threshold bands
vpvmas_upper = df_plot['vpvmas'] * 1.1  # Buy threshold
vpvmas_lower = df_plot['vpvmas'] * 0.8  # Sell threshold

ax2.fill_between(df_plot['timestamp'], vpvmas_upper, df_plot['vpvmas'],
                 color='green', alpha=0.1, label='Buy Zone (>1.1x signal)')
ax2.fill_between(df_plot['timestamp'], df_plot['vpvmas'], vpvmas_lower,
                 color='red', alpha=0.1, label='Sell Zone (<0.8x signal)')

# Mark signals on VPVMA chart too
ax2.scatter(buy_dates, df_plot[df_plot['buy_signal']]['vpvma'], 
            color='green', marker='^', s=100, zorder=5, edgecolors='black')
ax2.scatter(sell_dates, df_plot[df_plot['sell_signal']]['vpvma'], 
            color='red', marker='v', s=100, zorder=5, edgecolors='black')

# Zero line
ax2.axhline(y=0, color='gray', linestyle='-', linewidth=1, alpha=0.5)

ax2.set_ylabel('VPVMA Value', fontsize=12, fontweight='bold')
ax2.set_title('VPVMA Indicator with Threshold Bands', fontsize=12)
ax2.legend(loc='upper left', fontsize=9)
ax2.grid(True, alpha=0.3)

# Format x-axis
ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=max(1, lookback//252)))
plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45, ha='right')

# --- SUBPLOT 3: Signal Histogram ---
# Create signal array for visualization
signal_viz = np.zeros(len(df_plot))
signal_viz[df_plot['buy_signal'].values] = 1
signal_viz[df_plot['sell_signal'].values] = -1

colors = ['red' if x == -1 else 'green' if x == 1 else 'gray' for x in signal_viz]

ax3.bar(df_plot['timestamp'], signal_viz, color=colors, alpha=0.6, width=1)
ax3.set_ylabel('Signal', fontsize=12, fontweight='bold')
ax3.set_xlabel('Date', fontsize=12, fontweight='bold')
ax3.set_title('Trading Signals Timeline', fontsize=12)
ax3.set_ylim(-1.5, 1.5)
ax3.set_yticks([-1, 0, 1])
ax3.set_yticklabels(['SELL', 'HOLD', 'BUY'])
ax3.grid(True, alpha=0.3, axis='x')

# Format x-axis
ax3.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
ax3.xaxis.set_major_locator(mdates.MonthLocator(interval=max(1, lookback//252)))
plt.setp(ax3.xaxis.get_majorticklabels(), rotation=45, ha='right')

plt.tight_layout()

# Save
filename = f'{symbol}_vpvma_signals.png'
plt.savefig(filename, dpi=150, bbox_inches='tight')
print(f"\n✓ Chart saved as: {filename}")

# Show
print(f"✓ Displaying chart...")
plt.show()

# Summary stats
print(f"\n{'='*60}")
print("SIGNAL VALIDATION SUMMARY:")
print(f"{'='*60}")

print(f"\n📊 Period Analyzed: {df_plot['timestamp'].min().date()} to {df_plot['timestamp'].max().date()}")
print(f"   Trading days: {len(df_plot)}")

print(f"\n📈 Signals Generated:")
print(f"   Buy signals:  {buy_count}")
print(f"   Sell signals: {sell_count}")
print(f"   Total:        {buy_count + sell_count}")
print(f"   Signal frequency: {len(df_plot)/(buy_count + sell_count + 0.01):.1f} days between signals")

print(f"\n✓ Visual Validation Complete!")
print(f"  Check the chart to verify:")
print(f"  • Buy signals (green ▲) occur when VPVMA crosses above 1.1x signal line")
print(f"  • Sell signals (red ▼) occur when VPVMA crosses below 0.8x signal line")
print(f"  • Signals align with price trends")

print(f"\n{'='*60}")