import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.database import Database
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime

print("="*60)
print("DATA VALIDATION & VISUALIZATION")
print("="*60)

# Initialize database
db = Database(db_type='postgresql')

# Get available symbols
symbols = db.list_symbols()
print(f"\nAvailable symbols: {', '.join(symbols)}")

# Choose symbol
symbol = input(f"\nEnter symbol to validate (default: AAPL): ").upper() or 'AAPL'

if symbol not in symbols:
    print(f"❌ Symbol {symbol} not found!")
    exit(1)

print(f"\n{'='*60}")
print(f"VALIDATING: {symbol}")
print(f"{'='*60}")

# Get data
df = db.get_ohlcv_data(symbol)
info = db.get_data_info(symbol)

# Basic Statistics
print(f"\n📊 DATA SUMMARY:")
print(f"  Records: {len(df)}")
print(f"  Date Range: {info['start_date'].date()} to {info['end_date'].date()}")
print(f"  Duration: {(info['end_date'] - info['start_date']).days} days")

# Check for missing dates
df['date'] = pd.to_datetime(df['timestamp']).dt.date
date_gaps = []
for i in range(1, len(df)):
    gap = (pd.to_datetime(df.iloc[i]['timestamp']) - pd.to_datetime(df.iloc[i-1]['timestamp'])).days
    if gap > 5:  # More than 5 days (weekend + holidays)
        date_gaps.append((df.iloc[i-1]['date'], df.iloc[i]['date'], gap))

if date_gaps:
    print(f"\n⚠️  POTENTIAL DATE GAPS ({len(date_gaps)} found):")
    for start, end, gap in date_gaps[:5]:  # Show first 5
        print(f"    {start} → {end} ({gap} days)")
else:
    print(f"\n✓ No significant date gaps detected")

# Price Statistics
print(f"\n💰 PRICE STATISTICS:")
print(f"  High: ${df['high'].max():.2f}")
print(f"  Low: ${df['low'].min():.2f}")
print(f"  Latest Close: ${df['close'].iloc[-1]:.2f}")
print(f"  Price Range: ${df['high'].max() - df['low'].min():.2f}")

# Volume Statistics
print(f"\n📈 VOLUME STATISTICS:")
print(f"  Average Volume: {df['volume'].mean():,.0f}")
print(f"  Max Volume: {df['volume'].max():,.0f}")
print(f"  Min Volume: {df['volume'].min():,.0f}")

# Check for anomalies
zero_volume = (df['volume'] == 0).sum()
if zero_volume > 0:
    print(f"\n⚠️  WARNING: {zero_volume} days with zero volume")

# OHLC relationship validation
invalid_ohlc = []
for i, row in df.iterrows():
    if not (row['low'] <= row['open'] <= row['high'] and 
            row['low'] <= row['close'] <= row['high']):
        invalid_ohlc.append(i)

if invalid_ohlc:
    print(f"\n⚠️  WARNING: {len(invalid_ohlc)} records with invalid OHLC relationships")
else:
    print(f"\n✓ All OHLC relationships valid")

# Create visualizations
print(f"\n{'='*60}")
print("CREATING VISUALIZATIONS...")
print(f"{'='*60}")

# Set up the plot
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), gridspec_kw={'height_ratios': [3, 1]})
fig.suptitle(f'{symbol} - Data Validation ({info["start_date"].date()} to {info["end_date"].date()})', 
             fontsize=16, fontweight='bold')

# Price chart (candlestick-style using OHLC bars)
df['timestamp'] = pd.to_datetime(df['timestamp'])

# Determine color for each day (green = up, red = down)
colors = ['green' if df.iloc[i]['close'] >= df.iloc[i]['open'] else 'red' 
          for i in range(len(df))]

# Plot high-low lines
for i in range(len(df)):
    ax1.plot([df['timestamp'].iloc[i], df['timestamp'].iloc[i]], 
             [df['low'].iloc[i], df['high'].iloc[i]], 
             color=colors[i], linewidth=0.8, alpha=0.7)

# Plot close price line
ax1.plot(df['timestamp'], df['close'], color='blue', linewidth=1.5, 
         label='Close Price', alpha=0.8)

ax1.set_ylabel('Price ($)', fontsize=12, fontweight='bold')
ax1.set_title('Price Chart (OHLC)', fontsize=12)
ax1.grid(True, alpha=0.3)
ax1.legend()

# Format x-axis
ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45, ha='right')

# Volume chart
ax2.bar(df['timestamp'], df['volume'], color='steelblue', alpha=0.6, width=1)
ax2.set_ylabel('Volume', fontsize=12, fontweight='bold')
ax2.set_xlabel('Date', fontsize=12, fontweight='bold')
ax2.set_title('Trading Volume', fontsize=12)
ax2.grid(True, alpha=0.3)

# Format x-axis
ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45, ha='right')

# Format y-axis for volume
ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{x/1e6:.1f}M'))

plt.tight_layout()

# Save plot
filename = f'{symbol}_validation.png'
plt.savefig(filename, dpi=150, bbox_inches='tight')
print(f"\n✓ Chart saved as: {filename}")

# Show plot
print(f"✓ Displaying chart...")
plt.show()

# Recent data sample
print(f"\n{'='*60}")
print("RECENT DATA SAMPLE (Last 10 records):")
print(f"{'='*60}")
print(df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].tail(10).to_string(index=False))

# Data quality score
print(f"\n{'='*60}")
print("DATA QUALITY ASSESSMENT:")
print(f"{'='*60}")

score = 100
issues = []

if date_gaps:
    score -= 10
    issues.append(f"Date gaps detected ({len(date_gaps)})")

if zero_volume > 0:
    score -= 20
    issues.append(f"Zero volume days ({zero_volume})")

if invalid_ohlc:
    score -= 30
    issues.append(f"Invalid OHLC relationships ({len(invalid_ohlc)})")

if len(df) < 100:
    score -= 20
    issues.append(f"Limited data points ({len(df)})")

if score >= 90:
    print(f"✓ EXCELLENT - Data Quality Score: {score}/100")
elif score >= 70:
    print(f"⚠️  GOOD - Data Quality Score: {score}/100")
else:
    print(f"❌ POOR - Data Quality Score: {score}/100")

if issues:
    print(f"\nIssues found:")
    for issue in issues:
        print(f"  • {issue}")
else:
    print(f"\n✓ No issues detected - data is ready for VPVMA analysis!")

print(f"\n{'='*60}")
print("✓ Validation Complete!")
print(f"{'='*60}")

# Ask if user wants to validate another symbol
another = input("\nValidate another symbol? (y/n): ").lower()
if another == 'y':
    print("\nRestart script to validate another symbol")