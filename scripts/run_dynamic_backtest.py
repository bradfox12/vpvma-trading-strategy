"""
Execute Dynamic Backtest (2020-2025)
Main runner script with exports
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.database import Database
from scripts.dynamic_backtest.dynamic_universe_backtest import run_dynamic_backtest
import pandas as pd
from datetime import datetime

print("="*80)
print("DYNAMIC UNIVERSE BACKTEST - EXECUTION")
print("="*80)
print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("="*80)

# Configuration
CONFIG = {
    'start_date': '2005-01-01',
    'end_date': '2025-10-31',
    'initial_capital': 100000,
    'min_score': 75,      # Minimum trend score
    'top_n': 12,          # Number of stocks per universe
}

print("\n📋 CONFIGURATION:")
for key, value in CONFIG.items():
    print(f"  {key}: {value}")

# Initialize database
db = Database(db_type='postgresql')

# Run dynamic backtest
results = run_dynamic_backtest(
    db=db,
    start_date=CONFIG['start_date'],
    end_date=CONFIG['end_date'],
    initial_capital=CONFIG['initial_capital'],
    min_score=CONFIG['min_score'],
    top_n=CONFIG['top_n']
)

# Export results
print("\n" + "="*80)
print("EXPORTING RESULTS")
print("="*80)

# 1. Equity curve
equity_file = 'dynamic_backtest_equity_curve.csv'
results['history_df'].to_csv(equity_file, index=False)
print(f"✓ Equity curve: {equity_file}")

# 2. All trades
trades_file = 'dynamic_backtest_trades.csv'
results['trades_df'].to_csv(trades_file, index=False)
print(f"✓ Trades: {trades_file}")

# 3. Drawdown periods
if 'drawdown_periods' in results:
    dd_file = 'dynamic_backtest_drawdowns.csv'
    results['drawdown_periods'].to_csv(dd_file, index=False)
    print(f"✓ Drawdowns: {dd_file}")

# 4. Universe changes
if 'universe_changes' in results:
    universe_file = 'dynamic_backtest_universe_changes.csv'
    results['universe_changes'].to_csv(universe_file, index=False)
    print(f"✓ Universe changes: {universe_file}")

# 5. Monthly universe snapshots
universes = []
for date, data in results['monthly_universes'].items():
    for symbol in data['symbols']:
        score_row = data['scores'][data['scores']['symbol'] == symbol]
        if len(score_row) > 0:
            universes.append({
                'date': date,
                'symbol': symbol,
                'score': score_row.iloc[0]['score'],
                'return_6mo': score_row.iloc[0]['return_6mo'],
                'atr_pct': score_row.iloc[0]['atr_pct']
            })

universe_history_file = 'dynamic_backtest_universe_history.csv'
pd.DataFrame(universes).to_csv(universe_history_file, index=False)
print(f"✓ Universe history: {universe_history_file}")

# 6. Summary statistics
summary = {
    'metric': [
        'Total Return %',
        'Final Equity',
        'Max Drawdown %',
        'Number of Trades',
        'Win Rate %',
        'Average Win',
        'Average Loss',
        'Universe Changes',
        'Avg Drawdown Duration (days)',
        'Max Drawdown Duration (days)'
    ],
    'value': [
        f"{results['total_return_%']:.2f}",
        f"${results['final_equity']:,.0f}",
        f"{results['max_drawdown_%']:.2f}",
        results['num_trades'],
        f"{results['win_rate_%']:.1f}",
        f"${results['avg_win']:,.0f}",
        f"${results['avg_loss']:,.0f}",
        results['num_universe_changes'],
        f"{results['drawdown_periods']['duration_days'].mean():.0f}" if 'drawdown_periods' in results else 'N/A',
        f"{results['drawdown_periods']['duration_days'].max():.0f}" if 'drawdown_periods' in results else 'N/A'
    ]
}

summary_file = 'dynamic_backtest_summary.csv'
pd.DataFrame(summary).to_csv(summary_file, index=False)
print(f"✓ Summary: {summary_file}")

# Print key takeaways
print("\n" + "="*80)
print("KEY TAKEAWAYS")
print("="*80)

print(f"\n✅ PERFORMANCE:")
print(f"  Return: {results['total_return_%']:+.2f}%")
print(f"  Sharpe: {results['total_return_%'] / abs(results['max_drawdown_%']):.2f}")
print(f"  Max DD: {results['max_drawdown_%']:.2f}%")

if 'drawdown_periods' in results:
    dd_df = results['drawdown_periods']
    print(f"\n📉 DRAWDOWNS:")
    print(f"  Count: {len(dd_df)}")
    print(f"  Avg Duration: {dd_df['duration_days'].mean():.0f} days ({dd_df['duration_days'].mean()/30:.1f} months)")
    print(f"  Max Duration: {dd_df['duration_days'].max():.0f} days ({dd_df['duration_days'].max()/30:.1f} months)")
    print(f"  Median Duration: {dd_df['duration_days'].median():.0f} days")
    
    print(f"\n  🔍 Longest Drawdowns:")
    for idx, row in dd_df.sort_values('duration_days', ascending=False).head(3).iterrows():
        print(f"    {row['start_date']} to {row['end_date']}: {row['duration_days']} days ({row['max_drawdown_%']:.1f}%)")

print(f"\n🔄 UNIVERSE MANAGEMENT:")
print(f"  Total Rebalances: {results['num_universe_changes']}")
print(f"  Unique Stocks Traded: {len(set(results['trades_df']['symbol']))}")
print(f"  Avg Stocks/Universe: {CONFIG['top_n']}")

print(f"\n💼 TRADING ACTIVITY:")
print(f"  Total Trades: {results['num_trades']}")
print(f"  Win Rate: {results['win_rate_%']:.1f}%")
print(f"  Avg Trade Duration: {results['trades_df'][results['trades_df']['action']=='SELL']['hold_days'].mean():.0f} days")

print("\n" + "="*80)
print("BACKTEST COMPLETE")
print("="*80)
print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("\nNext: Run 'python scripts/compare_static_vs_dynamic.py' to compare results")