"""
Results Analyzer
================
Simple script to analyze and compare backtest results

Usage:
    python analyze_results.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
from research_config import *


def load_results():
    """Load training and validation results"""
    training_file = BACKTESTS_DIR / 'training_results.csv'
    validation_file = BACKTESTS_DIR / 'validation_results.csv'
    
    if not training_file.exists():
        print(f"❌ Training results not found: {training_file}")
        return None, None
    
    training = pd.read_csv(training_file)
    
    validation = None
    if validation_file.exists():
        validation = pd.read_csv(validation_file)
    
    return training, validation


def analyze_metric_consistency(df):
    """
    Analyze which metrics work consistently across windows
    
    Returns DataFrame with metric performance statistics
    """
    # Filter successful runs
    df = df[df['status'] == 'success'].copy()
    
    # Group by metric and universe size
    grouped = df.groupby(['metric', 'universe_size']).agg({
        'sharpe': ['mean', 'std', 'min', 'max'],
        'cagr': ['mean', 'std'],
        'win_rate': 'mean',
        'max_dd': 'mean',
        'window': 'count'  # Number of windows tested
    }).reset_index()
    
    # Flatten column names
    grouped.columns = ['_'.join(col).strip('_') for col in grouped.columns]
    
    # Rename for clarity
    grouped.rename(columns={
        'window_count': 'num_windows'
    }, inplace=True)
    
    # Calculate consistency score (how many windows beat baseline)
    baseline_sharpe = BASELINE_METRICS['sharpe']
    
    def count_wins(group):
        return (group['sharpe'] > baseline_sharpe).sum()
    
    wins = df.groupby(['metric', 'universe_size']).apply(count_wins).reset_index()
    wins.columns = ['metric', 'universe_size', 'windows_beat_baseline']
    
    # Merge
    result = grouped.merge(wins, on=['metric', 'universe_size'])
    
    # Calculate consistency percentage
    result['consistency_pct'] = (result['windows_beat_baseline'] / result['num_windows'] * 100)
    
    # Sort by average Sharpe
    result = result.sort_values('sharpe_mean', ascending=False)
    
    return result


def print_training_summary(df):
    """Print training results summary"""
    print("\n" + "="*80)
    print("TRAINING RESULTS SUMMARY")
    print("="*80)
    
    analysis = analyze_metric_consistency(df)
    
    print(f"\nTotal configurations tested: {len(df)}")
    print(f"Successful runs: {len(df[df['status'] == 'success'])}")
    print(f"Failed runs: {len(df[df['status'] != 'success'])}")
    
    print(f"\n📊 TOP 10 CONFIGURATIONS:")
    print("-" * 80)
    
    top_10 = analysis.head(10)
    
    for i, row in top_10.iterrows():
        print(f"\n{i+1}. {row['metric']} (Universe size: {int(row['universe_size'])})")
        print(f"   Sharpe: {row['sharpe_mean']:.3f} ± {row['sharpe_std']:.3f} (range: {row['sharpe_min']:.3f} - {row['sharpe_max']:.3f})")
        print(f"   CAGR: {row['cagr_mean']:.2f}% ± {row['cagr_std']:.2f}%")
        print(f"   Win Rate: {row['win_rate_mean']:.1f}%")
        print(f"   Max DD: {row['max_dd_mean']:.2f}%")
        print(f"   Consistency: {int(row['windows_beat_baseline'])}/{int(row['num_windows'])} windows beat baseline ({row['consistency_pct']:.0f}%)")
        
        # Compare to baseline
        sharpe_improvement = (row['sharpe_mean'] - BASELINE_METRICS['sharpe']) / BASELINE_METRICS['sharpe'] * 100
        cagr_improvement = row['cagr_mean'] - BASELINE_METRICS['cagr']
        
        if sharpe_improvement > 0:
            print(f"   ✅ Sharpe improvement: +{sharpe_improvement:.1f}% vs baseline")
        else:
            print(f"   ❌ Sharpe worse: {sharpe_improvement:.1f}% vs baseline")
        
        if cagr_improvement > 0:
            print(f"   ✅ CAGR improvement: +{cagr_improvement:.2f}% vs baseline")
        else:
            print(f"   ❌ CAGR worse: {cagr_improvement:.2f}% vs baseline")


def print_validation_summary(df):
    """Print validation results summary"""
    if df is None or len(df) == 0:
        print("\n⚠️  No validation results available")
        return
    
    print("\n" + "="*80)
    print("VALIDATION RESULTS (2024-2025 HOLDOUT)")
    print("="*80)
    
    # Filter successful runs
    df = df[df['status'] == 'success'].copy()
    
    if len(df) == 0:
        print("\n❌ All validation runs failed")
        return
    
    print(f"\nConfigurations tested: {len(df)}")
    
    # Keep the saved order: row 0 is the configuration chosen on TRAINING data.
    # Re-sorting by holdout Sharpe would turn the holdout into a selection step.
    print(f"\n📊 VALIDATION RESULTS (in training-rank order):")
    print("-" * 80)
    
    for i, row in df.iterrows():
        print(f"\n{i+1}. {row['metric']} (Universe size: {int(row['universe_size'])})")
        print(f"   Sharpe: {row['sharpe']:.3f}")
        print(f"   CAGR: {row['cagr']:.2f}%")
        print(f"   Win Rate: {row['win_rate']:.1f}%")
        print(f"   Max DD: {row['max_dd']:.2f}%")
        print(f"   Trades: {int(row['num_trades'])}")
        
        # Compare to baseline
        sharpe_vs_baseline = row['sharpe'] - BASELINE_METRICS['sharpe']
        cagr_vs_baseline = row['cagr'] - BASELINE_METRICS['cagr']
        
        if sharpe_vs_baseline > 0:
            print(f"   ✅ Beats baseline Sharpe by {sharpe_vs_baseline:.3f}")
        else:
            print(f"   ❌ Below baseline Sharpe by {abs(sharpe_vs_baseline):.3f}")
        
        if cagr_vs_baseline > 0:
            print(f"   ✅ Beats baseline CAGR by {cagr_vs_baseline:.2f}%")
        else:
            print(f"   ❌ Below baseline CAGR by {abs(cagr_vs_baseline):.2f}%")
    
    # The pre-registered choice is the top TRAINING configuration
    winner = df.iloc[0]
    print(f"\n" + "="*80)
    print(f"🏆 CHOSEN ON TRAINING DATA: {winner['metric']} (Universe size: {int(winner['universe_size'])})")
    if len(df) > 1:
        print("⚠️  Several configs were holdout-tested; only the first is an out-of-sample result.")
    print(f"="*80)
    print(f"Sharpe: {winner['sharpe']:.3f} (baseline: {BASELINE_METRICS['sharpe']:.3f})")
    print(f"CAGR: {winner['cagr']:.2f}% (baseline: {BASELINE_METRICS['cagr']:.2f}%)")
    print(f"Win Rate: {winner['win_rate']:.1f}% (baseline: {BASELINE_METRICS['win_rate']:.1f}%)")


def print_recommendations(training_df, validation_df):
    """Print implementation recommendations"""
    print("\n" + "="*80)
    print("💡 RECOMMENDATIONS")
    print("="*80)
    
    # Analyze consistency
    analysis = analyze_metric_consistency(training_df[training_df['status'] == 'success'])
    
    # Find most consistent
    most_consistent = analysis[analysis['consistency_pct'] >= 80].head(3)
    
    if len(most_consistent) > 0:
        print("\n✅ MOST CONSISTENT METRICS (work in 80%+ of windows):")
        for _, row in most_consistent.iterrows():
            print(f"   • {row['metric']} (size {int(row['universe_size'])}): {row['consistency_pct']:.0f}% consistency")
    
    # Find best validation performer
    if validation_df is not None and len(validation_df[validation_df['status'] == 'success']) > 0:
        val_winner = validation_df[validation_df['status'] == 'success'].iloc[0]
        
        print(f"\n✅ TRAINING-SELECTED CONFIG ON HOLDOUT:")
        print(f"   • {val_winner['metric']} (size {int(val_winner['universe_size'])})")
        print(f"   • Sharpe: {val_winner['sharpe']:.3f}")
        
        # Check if it's also consistent in training
        is_consistent = any(
            (analysis['metric'] == val_winner['metric']) & 
            (analysis['universe_size'] == val_winner['universe_size']) &
            (analysis['consistency_pct'] >= 60)
        )
        
        if is_consistent:
            print(f"   • ✅ Also consistent in training - STRONG CANDIDATE")
        else:
            print(f"   • ⚠️  Not consistent in training - proceed with caution")
    
    print(f"\n💡 IMPLEMENTATION STEPS:")
    print(f"   1. Review the winner's metric calculation in detail")
    print(f"   2. Implement dynamic universe selection in portfolio manager")
    print(f"   3. Refresh universe monthly (1st trading day)")
    print(f"   4. Track universe changes in a log file")
    print(f"   5. Monitor performance for 2-3 months before full deployment")


def main():
    """Main execution"""
    print("="*80)
    print("VPVMA UNIVERSE OPTIMIZATION - RESULTS ANALYSIS")
    print("="*80)
    
    # Load results
    training, validation = load_results()
    
    if training is None:
        print("\n❌ No results to analyze. Run batch_tester.py first.")
        return 1
    
    # Print summaries
    print_training_summary(training)
    print_validation_summary(validation)
    print_recommendations(training, validation)
    
    print("\n" + "="*80)
    print("ANALYSIS COMPLETE")
    print("="*80)
    
    return 0


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)