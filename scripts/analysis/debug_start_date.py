"""
Debug why trading doesn't start until 2012
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from data.database import Database
from scripts.dynamic_backtest.monthly_trend_selector import get_monthly_universes
import pandas as pd

print("="*80)
print("DEBUGGING START DATE ISSUE")
print("="*80)

db = Database(db_type='postgresql')

CONFIG = {
    'start_date': '2005-01-01',
    'end_date': '2025-10-31',
    'min_score': 85,
    'top_n': 20,
}

print(f"\n📅 CONFIG:")
print(f"  Start: {CONFIG['start_date']}")
print(f"  End: {CONFIG['end_date']}")
print(f"  Min Score: {CONFIG['min_score']}")

# Generate universes
print("\n🔍 Generating monthly universes...")
universes = get_monthly_universes(
    db, 
    CONFIG['start_date'], 
    CONFIG['end_date'],
    CONFIG['min_score'],
    CONFIG['top_n']
)

print(f"\n📊 UNIVERSE ANALYSIS:")
print(f"  Total months generated: {len(universes)}")

# Analyze by year
universe_df = []
for date, data in universes.items():
    universe_df.append({
        'date': date,
        'num_stocks': len(data['symbols']),
        'symbols': data['symbols']
    })

df = pd.DataFrame(universe_df)
df['date'] = pd.to_datetime(df['date'])
df['year'] = df['date'].dt.year

print("\n📅 Stocks per year:")
yearly = df.groupby('year')['num_stocks'].agg(['count', 'mean', 'min', 'max'])
print(yearly)

print("\n🔍 First 50 months:")
print(df[['date', 'num_stocks']].head(50))

# Find first month with stocks
first_with_stocks = df[df['num_stocks'] > 0].iloc[0]
print(f"\n✅ First month with ANY stocks: {first_with_stocks['date'].strftime('%Y-%m-%d')}")
print(f"   Stocks: {first_with_stocks['num_stocks']}")

# Find first month with 5+ stocks
first_with_5plus = df[df['num_stocks'] >= 5].iloc[0] if any(df['num_stocks'] >= 5) else None
if first_with_5plus is not None:
    print(f"\n✅ First month with 5+ stocks: {first_with_5plus['date'].strftime('%Y-%m-%d')}")
    print(f"   Stocks: {first_with_5plus['num_stocks']}")

# Find first month with 10+ stocks
first_with_10plus = df[df['num_stocks'] >= 10].iloc[0] if any(df['num_stocks'] >= 10) else None
if first_with_10plus is not None:
    print(f"\n✅ First month with 10+ stocks: {first_with_10plus['date'].strftime('%Y-%m-%d')}")
    print(f"   Stocks: {first_with_10plus['num_stocks']}")

# Check what the equity curve shows
print("\n" + "="*80)
print("COMPARING TO ACTUAL BACKTEST RESULTS")
print("="*80)

equity = pd.read_csv('dynamic_backtest_equity_curve.csv')
trades = pd.read_csv('dynamic_backtest_trades.csv')

actual_first_trade = trades[trades['action'] == 'BUY'].iloc[0]
print(f"\nActual first trade: {actual_first_trade['date']}")
print(f"Symbol: {actual_first_trade['symbol']}")

# Find what universe existed at that date
actual_date = pd.to_datetime(actual_first_trade['date'])
universe_at_first_trade = df[df['date'] <= actual_date].iloc[-1]
print(f"\nUniverse on {universe_at_first_trade['date'].strftime('%Y-%m-%d')}:")
print(f"  Stocks available: {universe_at_first_trade['num_stocks']}")

# Check if there were earlier universes with stocks
earlier_universes = df[(df['date'] < actual_date) & (df['num_stocks'] > 0)]
print(f"\n❗ Months BEFORE first trade with stocks available: {len(earlier_universes)}")
if len(earlier_universes) > 0:
    print("\nFirst 10 missed opportunities:")
    print(earlier_universes[['date', 'num_stocks', 'symbols']].head(10))

print("\n" + "="*80)
print("DIAGNOSIS")
print("="*80)

if len(earlier_universes) > 0:
    print(f"""
🚨 PROBLEM FOUND: Backtest skipping early years

The universe had {len(earlier_universes)} months with stocks available
BEFORE the first trade in {actual_first_trade['date']}.

This means the backtest logic is:
1. Either hardcoded to start later
2. Waiting for some threshold of stocks
3. Skipping months for some other reason

CHECK: dynamic_universe_backtest.py for:
- Hardcoded dates
- Minimum stock requirements before starting
- Data availability checks
""")
else:
    print("✅ Backtest started at first available opportunity")