"""
Parameter Sensitivity Analysis
Test if strategy results are robust across parameter variations

Questions:
1. How much do returns vary with different parameters?
2. Is there an "optimal" parameter set?
3. Does optimizing parameters help or hurt (overfitting)?
4. Which parameters matter most?
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.dynamic_backtest.dynamic_universe_backtest import run_dynamic_backtest
from data.database import Database
import pandas as pd
import numpy as np
from datetime import datetime
import itertools
import json

print("="*80)
print("PARAMETER SENSITIVITY ANALYSIS")
print("="*80)
print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("="*80)

# Database connection
db = Database(db_type='postgresql')

# Define parameter grid
PARAMETER_GRID = {
    'min_score': [70, 75, 80, 85],
    'top_n': [8, 10, 12, 15, 20],
}

# Fixed parameters
FIXED_PARAMS = {
    'start_date': '2005-01-01',
    'end_date': '2025-10-31',
    'initial_capital': 100000,
}

# Baseline (your current settings)
BASELINE = {
    'min_score': 75,
    'top_n': 12,
}

print(f"\n📋 TESTING PARAMETERS:")
print(f"  min_score: {PARAMETER_GRID['min_score']}")
print(f"  top_n: {PARAMETER_GRID['top_n']}")
print(f"\n  Baseline: min_score={BASELINE['min_score']}, top_n={BASELINE['top_n']}")
print(f"\n  Total combinations: {len(PARAMETER_GRID['min_score']) * len(PARAMETER_GRID['top_n'])}")
print(f"  Estimated time: {len(PARAMETER_GRID['min_score']) * len(PARAMETER_GRID['top_n']) * 45} minutes")
print("="*80)

# Generate all parameter combinations
param_combinations = list(itertools.product(
    PARAMETER_GRID['min_score'],
    PARAMETER_GRID['top_n']
))

results = []
run_number = 0

for min_score, top_n in param_combinations:
    run_number += 1
    
    print(f"\n{'='*80}")
    print(f"RUN {run_number}/{len(param_combinations)}")
    print(f"Parameters: min_score={min_score}, top_n={top_n}")
    print(f"{'='*80}")
    
    try:
        # Run backtest with these parameters
        backtest_results = run_dynamic_backtest(
            db=db,
            start_date=FIXED_PARAMS['start_date'],
            end_date=FIXED_PARAMS['end_date'],
            initial_capital=FIXED_PARAMS['initial_capital'],
            min_score=min_score,
            top_n=top_n
        )
        
        # Extract key metrics
        result = {
            'min_score': min_score,
            'top_n': top_n,
            'total_return_%': backtest_results['total_return_%'],
            'final_equity': backtest_results['final_equity'],
            'max_drawdown_%': backtest_results['max_drawdown_%'],
            'num_trades': backtest_results['num_trades'],
            'win_rate_%': backtest_results['win_rate_%'],
            'num_universe_changes': backtest_results['num_universe_changes'],
            'avg_win': backtest_results['avg_win'],
            'avg_loss': backtest_results['avg_loss'],
        }
        
        # Calculate additional metrics
        history_df = backtest_results['history_df']
        equity_curve = history_df['equity'].values
        
        # Calculate Sharpe-like metric (return / max_drawdown)
        result['return_to_dd_ratio'] = abs(result['total_return_%'] / result['max_drawdown_%'])
        
        # Calculate CAGR
        years = (pd.to_datetime(FIXED_PARAMS['end_date']) - 
                pd.to_datetime(FIXED_PARAMS['start_date'])).days / 365.25
        result['cagr_%'] = ((result['final_equity'] / FIXED_PARAMS['initial_capital']) ** (1/years) - 1) * 100
        
        # Mark if this is baseline
        result['is_baseline'] = (min_score == BASELINE['min_score'] and 
                                 top_n == BASELINE['top_n'])
        
        results.append(result)
        
        print(f"\n✓ Results:")
        print(f"  Total Return: {result['total_return_%']:.2f}%")
        print(f"  CAGR: {result['cagr_%']:.2f}%")
        print(f"  Max DD: {result['max_drawdown_%']:.2f}%")
        print(f"  Return/DD: {result['return_to_dd_ratio']:.2f}")
        print(f"  Trades: {result['num_trades']}")
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        results.append({
            'min_score': min_score,
            'top_n': top_n,
            'error': str(e),
            'is_baseline': False
        })
        continue

# Convert to DataFrame
results_df = pd.DataFrame(results)

# Save results
results_file = 'parameter_sensitivity_results.csv'
results_df.to_csv(results_file, index=False)
print(f"\n✓ Saved results to: {results_file}")

# Analysis
print("\n" + "="*80)
print("SENSITIVITY ANALYSIS")
print("="*80)

# Filter successful runs
successful_df = results_df[~results_df['total_return_%'].isna()].copy()

if len(successful_df) == 0:
    print("\n❌ No successful runs!")
    exit(1)

# Get baseline results
baseline_row = successful_df[successful_df['is_baseline']].iloc[0]

print(f"\n📊 BASELINE PERFORMANCE:")
print(f"  min_score={BASELINE['min_score']}, top_n={BASELINE['top_n']}")
print(f"  Total Return: {baseline_row['total_return_%']:.2f}%")
print(f"  CAGR: {baseline_row['cagr_%']:.2f}%")
print(f"  Max DD: {baseline_row['max_drawdown_%']:.2f}%")
print(f"  Return/DD: {baseline_row['return_to_dd_ratio']:.2f}")

# Find best/worst by different metrics
print(f"\n🏆 BEST PERFORMANCE BY METRIC:")

metrics = ['total_return_%', 'cagr_%', 'max_drawdown_%', 'return_to_dd_ratio']
for metric in metrics:
    if metric == 'max_drawdown_%':
        # Lower is better for drawdown
        best = successful_df.loc[successful_df[metric].idxmax()]  # Least negative
        print(f"\n  Best {metric}: {best[metric]:.2f}%")
    else:
        best = successful_df.loc[successful_df[metric].idxmax()]
        print(f"\n  Best {metric}: {best[metric]:.2f}%")
    
    print(f"    Parameters: min_score={int(best['min_score'])}, top_n={int(best['top_n'])}")
    
    # Compare to baseline
    baseline_value = baseline_row[metric]
    improvement = ((best[metric] - baseline_value) / abs(baseline_value)) * 100
    print(f"    vs Baseline: {improvement:+.1f}%")

# Analyze parameter stability
print(f"\n📈 PARAMETER STABILITY:")

# Group by each parameter
for param in ['min_score', 'top_n']:
    grouped = successful_df.groupby(param)['total_return_%'].agg(['mean', 'std', 'min', 'max'])
    
    print(f"\n  {param}:")
    for idx, row in grouped.iterrows():
        range_pct = ((row['max'] - row['min']) / row['mean']) * 100
        print(f"    {param}={int(idx)}: Mean={row['mean']:.1f}%, "
              f"StdDev={row['std']:.1f}%, Range={range_pct:.1f}%")

# Overall stability
total_return_std = successful_df['total_return_%'].std()
total_return_mean = successful_df['total_return_%'].mean()
coefficient_of_variation = (total_return_std / total_return_mean) * 100

print(f"\n📊 OVERALL STABILITY:")
print(f"  Mean Return: {total_return_mean:.2f}%")
print(f"  Std Dev: {total_return_std:.2f}%")
print(f"  Coefficient of Variation: {coefficient_of_variation:.2f}%")

if coefficient_of_variation < 10:
    print(f"  ✅ VERY STABLE - Results don't depend heavily on parameters")
elif coefficient_of_variation < 20:
    print(f"  ✅ STABLE - Parameters have moderate impact")
elif coefficient_of_variation < 30:
    print(f"  ⚠️  MODERATELY UNSTABLE - Parameter choice matters")
else:
    print(f"  ❌ UNSTABLE - Results highly dependent on parameters (overfitting risk)")

# Check for overfitting signs
print(f"\n🔍 OVERFITTING ANALYSIS:")

# If "optimal" parameters are at extremes, that's suspicious
best_return_row = successful_df.loc[successful_df['total_return_%'].idxmax()]
print(f"\n  Best return parameters: min_score={int(best_return_row['min_score'])}, top_n={int(best_return_row['top_n'])}")

extreme_params = (
    best_return_row['min_score'] in [min(PARAMETER_GRID['min_score']), max(PARAMETER_GRID['min_score'])] or
    best_return_row['top_n'] in [min(PARAMETER_GRID['top_n']), max(PARAMETER_GRID['top_n'])]
)

if extreme_params:
    print(f"  ⚠️  WARNING: Optimal parameters at grid extremes - possible overfitting")
    print(f"  ⚠️  Consider expanding parameter range to test further")
else:
    print(f"  ✅ Optimal parameters not at extremes - good sign")

# Baseline comparison
baseline_rank = (successful_df['total_return_%'] > baseline_row['total_return_%']).sum() + 1
total_configs = len(successful_df)
percentile = ((total_configs - baseline_rank + 1) / total_configs) * 100

print(f"\n📊 BASELINE RANK:")
print(f"  Rank: {baseline_rank}/{total_configs}")
print(f"  Percentile: {percentile:.0f}th")

if percentile >= 50:
    print(f"  ✅ Baseline is in top half - good default choice")
else:
    print(f"  ⚠️  Baseline below median - consider adjusting")

# Create summary report
summary = {
    'baseline': {
        'min_score': BASELINE['min_score'],
        'top_n': BASELINE['top_n'],
        'return': float(baseline_row['total_return_%']),
        'cagr': float(baseline_row['cagr_%']),
        'max_dd': float(baseline_row['max_drawdown_%']),
        'rank': int(baseline_rank),
        'percentile': float(percentile)
    },
    'best_return': {
        'min_score': int(best_return_row['min_score']),
        'top_n': int(best_return_row['top_n']),
        'return': float(best_return_row['total_return_%']),
        'improvement_vs_baseline': float(((best_return_row['total_return_%'] - baseline_row['total_return_%']) / baseline_row['total_return_%']) * 100)
    },
    'stability': {
        'coefficient_of_variation': float(coefficient_of_variation),
        'is_stable': bool(coefficient_of_variation < 20),
        'mean_return': float(total_return_mean),
        'std_dev': float(total_return_std)
    },
    'overfitting_risk': {
        'optimal_at_extremes': bool(extreme_params),
        'risk_level': 'HIGH' if extreme_params else 'LOW'
    },
    'recommendation': ''
}

# Generate recommendation
if coefficient_of_variation < 20 and not extreme_params and percentile >= 50:
    summary['recommendation'] = "✅ Strategy is ROBUST. Baseline parameters are good. Optimization provides minimal benefit."
elif coefficient_of_variation < 20 and percentile < 50:
    summary['recommendation'] = f"✅ Strategy is STABLE but consider: min_score={int(best_return_row['min_score'])}, top_n={int(best_return_row['top_n'])} for better performance."
elif coefficient_of_variation >= 30:
    summary['recommendation'] = "⚠️ Strategy is PARAMETER-SENSITIVE. High risk of overfitting. Use baseline and proceed with caution."
else:
    summary['recommendation'] = "⚠️ Strategy shows moderate parameter sensitivity. Baseline is acceptable but test thoroughly before live trading."

print(f"\n{'='*80}")
print("RECOMMENDATION")
print("="*80)
print(f"\n{summary['recommendation']}")

# Save summary
with open('parameter_sensitivity_summary.json', 'w') as f:
    json.dump(summary, f, indent=2)

print(f"\n✓ Saved summary to: parameter_sensitivity_summary.json")

print("\n" + "="*80)
print("ANALYSIS COMPLETE")
print("="*80)
print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("\nNext steps:")
print("1. Review parameter_sensitivity_results.csv")
print("2. Check if optimization helps or hurts")
print("3. Decide whether to adjust baseline parameters")
print("4. Consider walk-forward analysis for out-of-sample validation")