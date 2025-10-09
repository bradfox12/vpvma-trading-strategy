"""
Debug why parameter sensitivity gave different results
Compare the universes generated
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from data.database import Database
from scripts.dynamic_backtest.dynamic_universe_backtest import run_dynamic_backtest
import pandas as pd
from datetime import datetime

print("="*80)
print("DEBUG: Parameter Sensitivity vs Clean Run")
print("="*80)

db = Database(db_type='postgresql')

# Test with exact same parameters
CONFIG = {
    'start_date': '2005-01-01',
    'end_date': '2025-10-31',
    'initial_capital': 100000,
    'min_score': 85,
    'top_n': 20,
}

print("\n🔍 Running backtest with min_score=85, top_n=20...")
print("This should match the parameter sensitivity result if everything is correct")

results = run_dynamic_backtest(
    db=db,
    start_date=CONFIG['start_date'],
    end_date=CONFIG['end_date'],
    initial_capital=CONFIG['initial_capital'],
    min_score=CONFIG['min_score'],
    top_n=CONFIG['top_n']
)

print("\n📊 RESULTS:")
print(f"  Total Return: {results['total_return_%']:.2f}%")
print(f"  Final Equity: ${results['final_equity']:,.0f}")
print(f"  Total Trades: {results['num_trades']}")
print(f"  Universe Changes: {results['num_universe_changes']}")

# Analyze the monthly universes
print("\n🔍 UNIVERSE ANALYSIS:")

# Convert monthly_universes to DataFrame
universe_data = []
for date, data in results['monthly_universes'].items():
    universe_data.append({
        'date': date,
        'num_stocks': len(data['symbols']),
        'symbols': ', '.join(sorted(data['symbols'])[:5]) + ('...' if len(data['symbols']) > 5 else ''),
        'min_score': data['scores']['score'].min() if len(data['scores']) > 0 else None,
        'max_score': data['scores']['score'].max() if len(data['scores']) > 0 else None
    })

universe_df = pd.DataFrame(universe_data)
universe_df['date'] = pd.to_datetime(universe_df['date'])
universe_df['year'] = universe_df['date'].dt.year

print("\n📅 Stocks per Year:")
yearly = universe_df.groupby('year')['num_stocks'].agg(['mean', 'min', 'max'])
print(yearly)

print("\n📊 Years with Zero Stocks:")
zero_months = universe_df[universe_df['num_stocks'] == 0]
print(f"  Total months with 0 stocks: {len(zero_months)}")
if len(zero_months) > 0:
    print(f"  Years affected: {sorted(zero_months['year'].unique())}")

print("\n📊 Distribution of Universe Sizes:")
print(universe_df['num_stocks'].value_counts().sort_index())

# Check parameter sensitivity results
print("\n" + "="*80)
print("COMPARING TO PARAMETER SENSITIVITY RESULTS")
print("="*80)

try:
    param_results = pd.read_csv('parameter_sensitivity_results.csv')
    row_85_20 = param_results[(param_results['min_score']==85) & (param_results['top_n']==20)]
    
    if len(row_85_20) > 0:
        param_return = row_85_20.iloc[0]['total_return_%']
        param_trades = row_85_20.iloc[0]['num_trades']
        
        print("\nParameter Sensitivity Results (85, 20):")
        print(f"  Total Return: {param_return:.2f}%")
        print(f"  Total Trades: {param_trades}")
        
        print("\nThis Clean Run (85, 20):")
        print(f"  Total Return: {results['total_return_%']:.2f}%")
        print(f"  Total Trades: {results['num_trades']}")
        
        print("\n❗ DISCREPANCY:")
        return_diff = ((results['total_return_%'] / param_return) - 1) * 100
        trade_diff = ((results['num_trades'] / param_trades) - 1) * 100
        
        print(f"  Return difference: {return_diff:+.1f}%")
        print(f"  Trade difference: {trade_diff:+.1f}%")
        
        if abs(return_diff) > 10 or abs(trade_diff) > 10:
            print("\n🚨 SIGNIFICANT DIFFERENCE DETECTED!")
            print("  Parameter sensitivity results are NOT matching clean run")
            print("  This suggests a bug in the parameter sensitivity script")
    else:
        print("\n❌ No (85, 20) results found in parameter_sensitivity_results.csv")
        
except FileNotFoundError:
    print("\n❌ parameter_sensitivity_results.csv not found")

print("\n" + "="*80)
print("CHECKING MONTHLY_TREND_SELECTOR")
print("="*80)

# Check if min_score is actually being used
from scripts.dynamic_backtest.monthly_trend_selector import MonthlyTrendSelector

selector = MonthlyTrendSelector(db)

# Test on a specific date
test_date = '2020-06-01'
print(f"\nTesting universe selection for {test_date}:")

for min_score_test in [70, 75, 80, 85, 90]:
    universe = selector.get_monthly_universe(test_date, top_n=20, min_score=min_score_test)
    print(f"  min_score={min_score_test}: {len(universe)} stocks")
    if len(universe) > 0:
        scores = [s['score'] for s in universe]
        print(f"    Score range: {min(scores)}-{max(scores)}")

print("\n" + "="*80)
print("DIAGNOSIS")
print("="*80)

if results['num_trades'] < 400:  # Expected ~608
    print("""
🚨 PROBLEM IDENTIFIED:
    
The clean run is producing significantly fewer trades than parameter sensitivity.
    
Possible causes:
1. Parameter sensitivity script has a bug (most likely)
2. MonthlyTrendSelector not respecting min_score parameter
3. Different data between runs (cache issue?)
4. Stock universe changed between runs

RECOMMENDED ACTIONS:
1. Check if MonthlyTrendSelector.get_monthly_universe() uses min_score correctly
2. Re-run parameter sensitivity test with verbose logging
3. Compare universe_history.csv from both runs side-by-side
""")
else:
    print("""
✅ Results match parameter sensitivity
    
The discrepancy you saw earlier was likely a one-time issue.
Configuration (85, 20) is validated.
""")