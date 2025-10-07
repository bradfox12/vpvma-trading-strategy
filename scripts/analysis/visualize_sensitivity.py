"""
Visualize Parameter Sensitivity Results
Creates heatmaps and charts
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import json

print("="*80)
print("VISUALIZING PARAMETER SENSITIVITY")
print("="*80)

# Load results
results_df = pd.read_csv('parameter_sensitivity_results.csv')
successful_df = results_df[~results_df['total_return_%'].isna()].copy()

# Load or create summary
try:
    with open('parameter_sensitivity_summary.json', 'r') as f:
        summary = json.load(f)
    print("✓ Loaded summary from JSON")
except (FileNotFoundError, json.JSONDecodeError) as e:
    print("⚠️  JSON summary not found or corrupted, creating from CSV...")
    
    # Get baseline from CSV
    baseline_row = successful_df[(successful_df['min_score']==75) & (successful_df['top_n']==12)]
    
    if len(baseline_row) == 0:
        print("❌ Baseline configuration not found in results!")
        exit(1)
    
    baseline_row = baseline_row.iloc[0]
    
    summary = {
        'baseline': {
            'min_score': 75,
            'top_n': 12,
            'return': float(baseline_row['total_return_%']),
            'cagr': float(baseline_row['cagr_%']) if 'cagr_%' in baseline_row else 11.38,
            'max_dd': float(baseline_row['max_drawdown_%'])
        }
    }
    print("✓ Created summary from CSV")

# Set style
sns.set_style("whitegrid")
plt.rcParams['figure.figsize'] = (16, 12)

# Create figure with subplots
fig, axes = plt.subplots(2, 2, figsize=(16, 12))
fig.suptitle('Parameter Sensitivity Analysis - 20 Year Backtest (2005-2025)', 
             fontsize=16, fontweight='bold')

# 1. Total Return Heatmap
pivot_return = successful_df.pivot(index='min_score', columns='top_n', values='total_return_%')
sns.heatmap(pivot_return, annot=True, fmt='.0f', cmap='RdYlGn', ax=axes[0, 0],
            cbar_kws={'label': 'Total Return %'}, vmin=300, vmax=1200)
axes[0, 0].set_title('Total Return % by Parameters', fontsize=12, fontweight='bold')
axes[0, 0].set_xlabel('Portfolio Size (top_n)')
axes[0, 0].set_ylabel('Min Score Threshold')

# Mark baseline
baseline_ms = summary['baseline']['min_score']
baseline_tn = summary['baseline']['top_n']
baseline_col_idx = list(pivot_return.columns).index(baseline_tn)
baseline_row_idx = list(pivot_return.index).index(baseline_ms)
axes[0, 0].scatter([baseline_col_idx + 0.5], [baseline_row_idx + 0.5],
                   marker='*', s=800, color='blue', edgecolors='white', 
                   linewidths=3, label='Baseline', zorder=10)
axes[0, 0].legend(fontsize=10)

# 2. Max Drawdown Heatmap
pivot_dd = successful_df.pivot(index='min_score', columns='top_n', values='max_drawdown_%')
sns.heatmap(pivot_dd, annot=True, fmt='.1f', cmap='RdYlGn_r', ax=axes[0, 1],
            cbar_kws={'label': 'Max Drawdown %'})
axes[0, 1].set_title('Max Drawdown % by Parameters (lower is better)', fontsize=12, fontweight='bold')
axes[0, 1].set_xlabel('Portfolio Size (top_n)')
axes[0, 1].set_ylabel('Min Score Threshold')

# 3. Return/DD Ratio Heatmap
pivot_ratio = successful_df.pivot(index='min_score', columns='top_n', values='return_to_dd_ratio')
sns.heatmap(pivot_ratio, annot=True, fmt='.1f', cmap='RdYlGn', ax=axes[1, 0],
            cbar_kws={'label': 'Return/DD Ratio'})
axes[1, 0].set_title('Return/Drawdown Ratio (higher is better)', fontsize=12, fontweight='bold')
axes[1, 0].set_xlabel('Portfolio Size (top_n)')
axes[1, 0].set_ylabel('Min Score Threshold')

# 4. Number of Trades Heatmap
pivot_trades = successful_df.pivot(index='min_score', columns='top_n', values='num_trades')
sns.heatmap(pivot_trades, annot=True, fmt='.0f', cmap='YlOrRd', ax=axes[1, 1],
            cbar_kws={'label': 'Number of Trades'})
axes[1, 1].set_title('Total Trades Over 20 Years', fontsize=12, fontweight='bold')
axes[1, 1].set_xlabel('Portfolio Size (top_n)')
axes[1, 1].set_ylabel('Min Score Threshold')

plt.tight_layout()
plt.savefig('parameter_sensitivity_heatmaps.png', dpi=300, bbox_inches='tight')
print("\n✓ Saved: parameter_sensitivity_heatmaps.png")
plt.close()

# Create line plots
fig2, axes2 = plt.subplots(2, 2, figsize=(16, 10))
fig2.suptitle('Parameter Impact on Performance', fontsize=16, fontweight='bold')

# By min_score
grouped_score = successful_df.groupby('min_score').agg({
    'total_return_%': ['mean', 'std'],
    'max_drawdown_%': ['mean', 'std']
})

axes2[0, 0].errorbar(grouped_score.index, 
                     grouped_score[('total_return_%', 'mean')],
                     yerr=grouped_score[('total_return_%', 'std')],
                     marker='o', markersize=10, capsize=5, linewidth=2, color='darkblue')
axes2[0, 0].axhline(y=summary['baseline']['return'], color='r', linestyle='--', 
                    linewidth=2, label='Baseline', alpha=0.7)
axes2[0, 0].set_title('Total Return vs Min Score Threshold', fontsize=12, fontweight='bold')
axes2[0, 0].set_xlabel('Min Score', fontsize=11)
axes2[0, 0].set_ylabel('Total Return %', fontsize=11)
axes2[0, 0].legend(fontsize=10)
axes2[0, 0].grid(True, alpha=0.3)

# By top_n
grouped_topn = successful_df.groupby('top_n').agg({
    'total_return_%': ['mean', 'std'],
    'max_drawdown_%': ['mean', 'std']
})

axes2[0, 1].errorbar(grouped_topn.index, 
                     grouped_topn[('total_return_%', 'mean')],
                     yerr=grouped_topn[('total_return_%', 'std')],
                     marker='o', markersize=10, capsize=5, linewidth=2, color='darkgreen')
axes2[0, 1].axhline(y=summary['baseline']['return'], color='r', linestyle='--', 
                    linewidth=2, label='Baseline', alpha=0.7)
axes2[0, 1].set_title('Total Return vs Portfolio Size', fontsize=12, fontweight='bold')
axes2[0, 1].set_xlabel('Portfolio Size (top_n)', fontsize=11)
axes2[0, 1].set_ylabel('Total Return %', fontsize=11)
axes2[0, 1].legend(fontsize=10)
axes2[0, 1].grid(True, alpha=0.3)

# Drawdown by min_score
axes2[1, 0].errorbar(grouped_score.index, 
                     grouped_score[('max_drawdown_%', 'mean')],
                     yerr=grouped_score[('max_drawdown_%', 'std')],
                     marker='o', markersize=10, capsize=5, linewidth=2, color='darkorange')
axes2[1, 0].axhline(y=summary['baseline']['max_dd'], color='r', linestyle='--', 
                    linewidth=2, label='Baseline', alpha=0.7)
axes2[1, 0].set_title('Max Drawdown vs Min Score Threshold', fontsize=12, fontweight='bold')
axes2[1, 0].set_xlabel('Min Score', fontsize=11)
axes2[1, 0].set_ylabel('Max Drawdown %', fontsize=11)
axes2[1, 0].legend(fontsize=10)
axes2[1, 0].grid(True, alpha=0.3)

# Drawdown by top_n
axes2[1, 1].errorbar(grouped_topn.index, 
                     grouped_topn[('max_drawdown_%', 'mean')],
                     yerr=grouped_topn[('max_drawdown_%', 'std')],
                     marker='o', markersize=10, capsize=5, linewidth=2, color='darkred')
axes2[1, 1].axhline(y=summary['baseline']['max_dd'], color='r', linestyle='--', 
                    linewidth=2, label='Baseline', alpha=0.7)
axes2[1, 1].set_title('Max Drawdown vs Portfolio Size', fontsize=12, fontweight='bold')
axes2[1, 1].set_xlabel('Portfolio Size (top_n)', fontsize=11)
axes2[1, 1].set_ylabel('Max Drawdown %', fontsize=11)
axes2[1, 1].legend(fontsize=10)
axes2[1, 1].grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig('parameter_sensitivity_lines.png', dpi=300, bbox_inches='tight')
print("✓ Saved: parameter_sensitivity_lines.png")
plt.close()

print("\n" + "="*80)
print("VISUALIZATION COMPLETE")
print("="*80)
print("\nFiles created:")
print("  - parameter_sensitivity_heatmaps.png")
print("  - parameter_sensitivity_lines.png")
print("\n📊 Open these images to analyze the parameter landscape!")