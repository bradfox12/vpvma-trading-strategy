"""
Professional Backtest Visualization Generator
Creates industry-grade charts for presentation

Usage:
    python scripts/analysis/generate_presentation_visuals.py
    
Output:
    - presentation_equity_curve.png
    - presentation_drawdown_analysis.png
    - presentation_universe_adaptation.png
    - presentation_performance_summary.png
    - presentation_trade_analysis.png
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle
import seaborn as sns
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# Set professional style
plt.style.use('seaborn-v0_8-darkgrid')
sns.set_palette("husl")

# Professional color scheme
COLOR_PRIMARY = '#2563eb'      # Blue
COLOR_SECONDARY = '#64748b'    # Gray
COLOR_POSITIVE = '#22c55e'     # Green
COLOR_NEGATIVE = '#ef4444'     # Red
COLOR_WARNING = '#f59e0b'      # Amber
COLOR_ACCENT = '#8b5cf6'       # Purple

def load_data():
    """Load all backtest CSV files"""
    print("Loading backtest data...")
    
    equity = pd.read_csv('dynamic_backtest_equity_curve.csv')
    equity['date'] = pd.to_datetime(equity['date'])
    
    trades = pd.read_csv('dynamic_backtest_trades.csv')
    trades['date'] = pd.to_datetime(trades['date'])
    
    drawdowns = pd.read_csv('dynamic_backtest_drawdowns.csv')
    drawdowns['start_date'] = pd.to_datetime(drawdowns['start_date'])
    drawdowns['end_date'] = pd.to_datetime(drawdowns['end_date'])
    
    universe = pd.read_csv('dynamic_backtest_universe_history.csv')
    universe['date'] = pd.to_datetime(universe['date'])
    
    summary = pd.read_csv('dynamic_backtest_summary.csv')
    
    print(f"✓ Loaded {len(equity)} equity points")
    print(f"✓ Loaded {len(trades)} trades")
    print(f"✓ Loaded {len(drawdowns)} drawdown periods")
    print(f"✓ Loaded {len(universe)} universe entries")
    
    return equity, trades, drawdowns, universe, summary

def create_equity_curve(equity):
    """
    Chart 1: Professional Equity Curve with Crisis Periods
    """
    print("\n📊 Creating equity curve...")
    
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), 
                                     gridspec_kw={'height_ratios': [3, 1]})
    
    # Calculate returns
    equity['returns'] = equity['equity'].pct_change()
    equity['cumulative_return'] = ((equity['equity'] / equity['equity'].iloc[0]) - 1) * 100
    
    # Main equity curve
    ax1.plot(equity['date'], equity['equity'], 
             linewidth=2.5, color=COLOR_PRIMARY, label='Strategy Equity', zorder=3)
    ax1.fill_between(equity['date'], equity['equity'], 
                     alpha=0.3, color=COLOR_PRIMARY)
    
    # Add benchmark (SPY-like performance ~10% CAGR)
    years = (equity['date'].iloc[-1] - equity['date'].iloc[0]).days / 365.25
    benchmark_final = equity['equity'].iloc[0] * (1.10 ** years)
    benchmark = np.linspace(equity['equity'].iloc[0], benchmark_final, len(equity))
    ax1.plot(equity['date'], benchmark, 
             linewidth=2, color=COLOR_SECONDARY, linestyle='--', 
             label='10% CAGR Benchmark', alpha=0.7, zorder=2)
    
    # Shade crisis periods
    crisis_periods = [
        ('2008-09-01', '2009-03-31', '2008 Financial Crisis'),
        ('2020-02-15', '2020-03-31', 'COVID Crash'),
        ('2022-01-01', '2022-10-31', '2022 Bear Market')
    ]
    
    for start, end, label in crisis_periods:
        start_date = pd.to_datetime(start)
        end_date = pd.to_datetime(end)
        ax1.axvspan(start_date, end_date, alpha=0.15, color=COLOR_NEGATIVE, zorder=1)
        
        # Add label
        mid_date = start_date + (end_date - start_date) / 2
        ax1.text(mid_date, ax1.get_ylim()[1] * 0.95, label, 
                ha='center', va='top', fontsize=9, 
                color=COLOR_NEGATIVE, fontweight='bold',
                bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8))
    
    # Formatting
    ax1.set_ylabel('Portfolio Value ($)', fontsize=12, fontweight='bold')
    ax1.set_title('VPVMA Dynamic Universe Strategy - 20 Year Performance (2005-2025)', 
                  fontsize=14, fontweight='bold', pad=20)
    ax1.legend(loc='upper left', fontsize=11, framealpha=0.95)
    ax1.grid(True, alpha=0.3, linestyle='--')
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x/1e6:.2f}M' if x >= 1e6 else f'${x/1e3:.0f}K'))
    
    # Add key metrics box
    final_value = equity['equity'].iloc[-1]
    initial_value = equity['equity'].iloc[0]
    total_return = ((final_value / initial_value) - 1) * 100
    cagr = ((final_value / initial_value) ** (1 / years) - 1) * 100
    
    metrics_text = f"Initial: ${initial_value:,.0f}\nFinal: ${final_value:,.0f}\nReturn: +{total_return:.2f}%\nCAGR: {cagr:.2f}%"
    ax1.text(0.98, 0.05, metrics_text, transform=ax1.transAxes,
             fontsize=10, verticalalignment='bottom', horizontalalignment='right',
             bbox=dict(boxstyle='round', facecolor='white', alpha=0.9, edgecolor=COLOR_PRIMARY, linewidth=2))
    
    # Drawdown chart below
    running_max = equity['equity'].expanding().max()
    drawdown = (equity['equity'] - running_max) / running_max * 100
    
    ax2.fill_between(equity['date'], drawdown, 0, 
                     where=(drawdown < 0), color=COLOR_NEGATIVE, alpha=0.6, label='Drawdown')
    ax2.plot(equity['date'], drawdown, color=COLOR_NEGATIVE, linewidth=1.5)
    ax2.axhline(y=0, color='black', linestyle='-', linewidth=0.8)
    ax2.set_ylabel('Drawdown (%)', fontsize=11, fontweight='bold')
    ax2.set_xlabel('Date', fontsize=11, fontweight='bold')
    ax2.grid(True, alpha=0.3, linestyle='--')
    ax2.legend(loc='lower right', fontsize=10)
    
    # Format x-axis
    for ax in [ax1, ax2]:
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
        ax.xaxis.set_major_locator(mdates.YearLocator(2))
    
    plt.tight_layout()
    plt.savefig('presentation_equity_curve.png', dpi=300, bbox_inches='tight', facecolor='white')
    print("✓ Saved: presentation_equity_curve.png")
    plt.close()

def create_drawdown_analysis(drawdowns, equity):
    """
    Chart 2: Drawdown Analysis
    """
    print("\n📊 Creating drawdown analysis...")
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    
    # Top 10 longest drawdowns
    top_dd = drawdowns.nlargest(10, 'duration_days')
    
    colors = [COLOR_NEGATIVE if abs(dd) > 15 else COLOR_WARNING if abs(dd) > 10 else COLOR_PRIMARY 
              for dd in top_dd['max_drawdown_%']]
    
    ax1.barh(range(len(top_dd)), top_dd['duration_days'], color=colors, alpha=0.8)
    ax1.set_yticks(range(len(top_dd)))
    ax1.set_yticklabels([f"{row['start_date'].strftime('%b %Y')}\n{row['max_drawdown_%']:.1f}%" 
                         for _, row in top_dd.iterrows()], fontsize=9)
    ax1.set_xlabel('Duration (Days)', fontsize=11, fontweight='bold')
    ax1.set_title('Top 10 Longest Drawdown Periods', fontsize=12, fontweight='bold')
    ax1.grid(True, alpha=0.3, axis='x')
    ax1.invert_yaxis()
    
    # Add duration labels
    for i, (idx, row) in enumerate(top_dd.iterrows()):
        ax1.text(row['duration_days'] + 10, i, f"{row['duration_days']} days", 
                va='center', fontsize=9, fontweight='bold')
    
    # Drawdown depth distribution
    ax2.hist(drawdowns['max_drawdown_%'], bins=30, color=COLOR_PRIMARY, alpha=0.7, edgecolor='black')
    ax2.axvline(drawdowns['max_drawdown_%'].median(), color=COLOR_NEGATIVE, 
                linestyle='--', linewidth=2, label=f"Median: {drawdowns['max_drawdown_%'].median():.1f}%")
    ax2.axvline(drawdowns['max_drawdown_%'].mean(), color=COLOR_WARNING, 
                linestyle='--', linewidth=2, label=f"Mean: {drawdowns['max_drawdown_%'].mean():.1f}%")
    ax2.set_xlabel('Drawdown Depth (%)', fontsize=11, fontweight='bold')
    ax2.set_ylabel('Frequency', fontsize=11, fontweight='bold')
    ax2.set_title('Drawdown Depth Distribution', fontsize=12, fontweight='bold')
    ax2.legend(fontsize=10)
    ax2.grid(True, alpha=0.3, axis='y')
    
    plt.suptitle('Drawdown Analysis - Risk Management Performance', 
                 fontsize=14, fontweight='bold', y=1.02)
    plt.tight_layout()
    plt.savefig('presentation_drawdown_analysis.png', dpi=300, bbox_inches='tight', facecolor='white')
    print("✓ Saved: presentation_drawdown_analysis.png")
    plt.close()

def create_universe_adaptation(universe):
    """
    Chart 3: Universe Size Adaptation Over Time
    """
    print("\n📊 Creating universe adaptation chart...")
    
    fig, ax = plt.subplots(figsize=(14, 7))
    
    # Calculate monthly universe sizes
    monthly = universe.groupby(universe['date'].dt.to_period('M')).size()
    monthly.index = monthly.index.to_timestamp()
    
    # Plot
    ax.fill_between(monthly.index, monthly.values, alpha=0.4, color=COLOR_PRIMARY)
    ax.plot(monthly.index, monthly.values, linewidth=2.5, color=COLOR_PRIMARY, marker='o', 
            markersize=3, label='Qualifying Stocks per Month')
    
    # Add threshold lines
    ax.axhline(y=20, color=COLOR_POSITIVE, linestyle='--', linewidth=2, 
               alpha=0.7, label='Max Universe Size (20)')
    ax.axhline(y=5, color=COLOR_WARNING, linestyle='--', linewidth=2, 
               alpha=0.7, label='Defensive Threshold (5)')
    ax.axhline(y=2, color=COLOR_NEGATIVE, linestyle='--', linewidth=2, 
               alpha=0.7, label='High Risk Threshold (2)')
    
    # Shade regime periods
    regimes = [
        ('2008-01-01', '2009-12-31', 'Crisis', COLOR_NEGATIVE),
        ('2020-03-01', '2021-12-31', 'Bull Run', COLOR_POSITIVE),
        ('2022-01-01', '2022-12-31', 'Bear', COLOR_NEGATIVE),
    ]
    
    for start, end, label, color in regimes:
        start_date = pd.to_datetime(start)
        end_date = pd.to_datetime(end)
        ax.axvspan(start_date, end_date, alpha=0.1, color=color, zorder=0)
        
        # Add label at top
        mid_date = start_date + (end_date - start_date) / 2
        ax.text(mid_date, ax.get_ylim()[1] * 0.95, label, 
               ha='center', va='top', fontsize=10, fontweight='bold',
               bbox=dict(boxstyle='round,pad=0.4', facecolor='white', alpha=0.9, edgecolor=color))
    
    # Formatting
    ax.set_xlabel('Date', fontsize=12, fontweight='bold')
    ax.set_ylabel('Number of Stocks', fontsize=12, fontweight='bold')
    ax.set_title('Dynamic Universe Adaptation - Regime-Based Exposure Management', 
                 fontsize=14, fontweight='bold', pad=20)
    ax.legend(loc='upper left', fontsize=11, framealpha=0.95)
    ax.grid(True, alpha=0.3, linestyle='--')
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax.xaxis.set_major_locator(mdates.YearLocator(2))
    
    # Add statistics box
    stats_text = f"Mean: {monthly.mean():.1f} stocks/month\nMedian: {monthly.median():.0f}\nMin: {monthly.min():.0f} | Max: {monthly.max():.0f}\nMonths with 0 stocks: {(monthly == 0).sum()}"
    ax.text(0.98, 0.35, stats_text, transform=ax.transAxes,
            fontsize=10, verticalalignment='top', horizontalalignment='right',
            bbox=dict(boxstyle='round', facecolor='white', alpha=0.9, edgecolor=COLOR_PRIMARY, linewidth=2))
    
    plt.tight_layout()
    plt.savefig('presentation_universe_adaptation.png', dpi=300, bbox_inches='tight', facecolor='white')
    print("✓ Saved: presentation_universe_adaptation.png")
    plt.close()

def create_performance_summary(summary, trades, equity):
    """
    Chart 4: Performance Metrics Dashboard
    """
    print("\n📊 Creating performance summary...")
    
    fig = plt.figure(figsize=(14, 10))
    gs = fig.add_gridspec(3, 3, hspace=0.4, wspace=0.3)
    
    # Parse summary data
    metrics_dict = dict(zip(summary['metric'], summary['value']))
    
    # Large metric boxes (top row)
    metric_boxes = [
        ('Total Return', metrics_dict['Total Return %'], COLOR_POSITIVE),
        ('CAGR', f"{float(metrics_dict['Total Return %'].replace('%',''))/20:.2f}%", COLOR_PRIMARY),
        ('Max Drawdown', metrics_dict['Max Drawdown %'], COLOR_NEGATIVE),
    ]
    
    for idx, (title, value, color) in enumerate(metric_boxes):
        ax = fig.add_subplot(gs[0, idx])
        ax.text(0.5, 0.6, value, ha='center', va='center', 
               fontsize=36, fontweight='bold', color=color)
        ax.text(0.5, 0.2, title, ha='center', va='center', 
               fontsize=14, fontweight='bold', color='black')
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis('off')
        ax.add_patch(Rectangle((0.05, 0.05), 0.9, 0.9, 
                               fill=False, edgecolor=color, linewidth=3))
    
    # Trade statistics (middle row, left)
    ax_trades = fig.add_subplot(gs[1, 0])
    
    buy_trades = trades[trades['action'] == 'BUY']
    sell_trades = trades[trades['action'] == 'SELL']
    winning_trades = sell_trades[sell_trades['pnl'] > 0]
    losing_trades = sell_trades[sell_trades['pnl'] <= 0]
    
    trade_stats = {
        'Total Trades': len(sell_trades),
        'Winners': len(winning_trades),
        'Losers': len(losing_trades),
        'Win Rate': f"{(len(winning_trades)/len(sell_trades)*100):.1f}%"
    }
    
    y_pos = [3, 2, 1, 0]
    values = [trade_stats['Total Trades'], trade_stats['Winners'], 
              trade_stats['Losers'], 0]
    labels = ['Total Trades', 'Winners', 'Losers', 'Win Rate']
    colors_bar = [COLOR_PRIMARY, COLOR_POSITIVE, COLOR_NEGATIVE, COLOR_ACCENT]
    
    ax_trades.barh(y_pos[:3], values[:3], color=colors_bar[:3], alpha=0.8)
    ax_trades.set_yticks(y_pos)
    ax_trades.set_yticklabels(labels, fontsize=11)
    ax_trades.set_xlabel('Count', fontsize=11, fontweight='bold')
    ax_trades.set_title('Trade Statistics', fontsize=12, fontweight='bold')
    ax_trades.grid(True, alpha=0.3, axis='x')
    
    # Add win rate text
    ax_trades.text(0.95, 0.05, f"Win Rate: {trade_stats['Win Rate']}", 
                  transform=ax_trades.transAxes, fontsize=14, fontweight='bold',
                  ha='right', va='bottom', color=COLOR_PRIMARY,
                  bbox=dict(boxstyle='round', facecolor='white', edgecolor=COLOR_PRIMARY, linewidth=2))
    
    # Monthly returns distribution (middle row, center)
    ax_returns = fig.add_subplot(gs[1, 1])
    
    equity['month'] = equity['date'].dt.to_period('M')
    monthly_returns = equity.groupby('month')['equity'].last().pct_change() * 100
    monthly_returns = monthly_returns.dropna()
    
    ax_returns.hist(monthly_returns, bins=30, color=COLOR_PRIMARY, alpha=0.7, edgecolor='black')
    ax_returns.axvline(monthly_returns.median(), color=COLOR_POSITIVE, 
                      linestyle='--', linewidth=2, label=f'Median: {monthly_returns.median():.2f}%')
    ax_returns.axvline(0, color='black', linestyle='-', linewidth=1)
    ax_returns.set_xlabel('Monthly Return (%)', fontsize=11, fontweight='bold')
    ax_returns.set_ylabel('Frequency', fontsize=11, fontweight='bold')
    ax_returns.set_title('Monthly Return Distribution', fontsize=12, fontweight='bold')
    ax_returns.legend(fontsize=10)
    ax_returns.grid(True, alpha=0.3, axis='y')
    
    # Risk metrics (middle row, right)
    ax_risk = fig.add_subplot(gs[1, 2])
    ax_risk.axis('off')
    
    # Calculate additional metrics
    years = (equity['date'].iloc[-1] - equity['date'].iloc[0]).days / 365.25
    total_return = float(metrics_dict['Total Return %'].replace('%', ''))
    max_dd = float(metrics_dict['Max Drawdown %'].replace('%', ''))
    sharpe_proxy = total_return / abs(max_dd)
    
    risk_metrics = [
        ('Risk-Adjusted Return', f'{sharpe_proxy:.2f}x'),
        ('Max Drawdown', metrics_dict['Max Drawdown %']),
        ('Avg Trade Duration', f"{sell_trades['hold_days'].mean():.0f} days"),
        ('Total Trades', metrics_dict['Number of Trades']),
    ]
    
    y_start = 0.85
    for i, (label, value) in enumerate(risk_metrics):
        y = y_start - (i * 0.2)
        ax_risk.text(0.1, y, label, fontsize=11, fontweight='bold', va='top')
        ax_risk.text(0.9, y, value, fontsize=14, fontweight='bold', 
                    color=COLOR_PRIMARY, va='top', ha='right')
    
    ax_risk.set_title('Risk Metrics', fontsize=12, fontweight='bold', pad=20)
    
    # Cumulative returns by year (bottom row, spanning all columns)
    ax_yearly = fig.add_subplot(gs[2, :])
    
    equity['year'] = equity['date'].dt.year
    yearly_returns = equity.groupby('year')['equity'].agg(['first', 'last'])
    yearly_returns['return'] = ((yearly_returns['last'] / yearly_returns['first']) - 1) * 100
    
    colors_yearly = [COLOR_POSITIVE if r > 0 else COLOR_NEGATIVE for r in yearly_returns['return']]
    ax_yearly.bar(yearly_returns.index, yearly_returns['return'], 
                 color=colors_yearly, alpha=0.8, edgecolor='black')
    ax_yearly.axhline(y=0, color='black', linestyle='-', linewidth=1)
    ax_yearly.set_xlabel('Year', fontsize=11, fontweight='bold')
    ax_yearly.set_ylabel('Annual Return (%)', fontsize=11, fontweight='bold')
    ax_yearly.set_title('Annual Returns by Year', fontsize=12, fontweight='bold')
    ax_yearly.grid(True, alpha=0.3, axis='y')
    
    # Add value labels on bars
    for idx, (year, row) in enumerate(yearly_returns.iterrows()):
        height = row['return']
        ax_yearly.text(year, height + (2 if height > 0 else -2), 
                      f'{height:.1f}%', ha='center', 
                      va='bottom' if height > 0 else 'top',
                      fontsize=8, fontweight='bold')
    
    plt.suptitle('Performance Summary - 20 Year Backtest (2005-2025)', 
                 fontsize=16, fontweight='bold', y=0.98)
    plt.savefig('presentation_performance_summary.png', dpi=300, bbox_inches='tight', facecolor='white')
    print("✓ Saved: presentation_performance_summary.png")
    plt.close()

def create_trade_analysis(trades):
    """
    Chart 5: Trade Analysis
    """
    print("\n📊 Creating trade analysis...")
    
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(14, 10))
    
    sell_trades = trades[trades['action'] == 'SELL'].copy()
    
    # Win/Loss distribution
    winners = sell_trades[sell_trades['pnl'] > 0]
    losers = sell_trades[sell_trades['pnl'] <= 0]
    
    ax1.hist([winners['pnl_pct'], losers['pnl_pct']], 
             bins=30, label=['Winners', 'Losers'], 
             color=[COLOR_POSITIVE, COLOR_NEGATIVE], alpha=0.7)
    ax1.axvline(x=0, color='black', linestyle='-', linewidth=1)
    ax1.set_xlabel('Return per Trade (%)', fontsize=11, fontweight='bold')
    ax1.set_ylabel('Frequency', fontsize=11, fontweight='bold')
    ax1.set_title('Win/Loss Distribution', fontsize=12, fontweight='bold')
    ax1.legend(fontsize=10)
    ax1.grid(True, alpha=0.3, axis='y')
    
    # Hold time vs Return
    ax2.scatter(sell_trades['hold_days'], sell_trades['pnl_pct'], 
               c=[COLOR_POSITIVE if p > 0 else COLOR_NEGATIVE for p in sell_trades['pnl_pct']],
               alpha=0.6, s=50, edgecolors='black', linewidth=0.5)
    ax2.axhline(y=0, color='black', linestyle='--', linewidth=1)
    ax2.set_xlabel('Hold Days', fontsize=11, fontweight='bold')
    ax2.set_ylabel('Return (%)', fontsize=11, fontweight='bold')
    ax2.set_title('Hold Time vs Return', fontsize=12, fontweight='bold')
    ax2.grid(True, alpha=0.3)
    
    # Trades over time
    trades_by_month = trades.groupby(trades['date'].dt.to_period('M')).size()
    trades_by_month.index = trades_by_month.index.to_timestamp()
    
    ax3.bar(trades_by_month.index, trades_by_month.values, 
           width=20, color=COLOR_PRIMARY, alpha=0.7, edgecolor='black')
    ax3.set_xlabel('Date', fontsize=11, fontweight='bold')
    ax3.set_ylabel('Number of Trades', fontsize=11, fontweight='bold')
    ax3.set_title('Trading Activity Over Time', fontsize=12, fontweight='bold')
    ax3.grid(True, alpha=0.3, axis='y')
    ax3.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax3.xaxis.set_major_locator(mdates.YearLocator(2))
    
    # Top traded symbols
    symbol_counts = sell_trades['symbol'].value_counts().head(10)
    
    ax4.barh(range(len(symbol_counts)), symbol_counts.values, 
            color=COLOR_ACCENT, alpha=0.8, edgecolor='black')
    ax4.set_yticks(range(len(symbol_counts)))
    ax4.set_yticklabels(symbol_counts.index, fontsize=10)
    ax4.set_xlabel('Number of Trades', fontsize=11, fontweight='bold')
    ax4.set_title('Top 10 Most Traded Symbols', fontsize=12, fontweight='bold')
    ax4.grid(True, alpha=0.3, axis='x')
    ax4.invert_yaxis()
    
    # Add count labels
    for i, count in enumerate(symbol_counts.values):
        ax4.text(count + 0.5, i, str(count), va='center', fontsize=9, fontweight='bold')
    
    plt.suptitle('Trade Analysis - Execution Statistics', 
                 fontsize=14, fontweight='bold', y=0.995)
    plt.tight_layout()
    plt.savefig('presentation_trade_analysis.png', dpi=300, bbox_inches='tight', facecolor='white')
    print("✓ Saved: presentation_trade_analysis.png")
    plt.close()

def main():
    """Generate all presentation visualizations"""
    print("="*80)
    print("PROFESSIONAL PRESENTATION VISUALIZATIONS")
    print("="*80)
    
    # Load data
    equity, trades, drawdowns, universe, summary = load_data()
    
    # Generate all charts
    create_equity_curve(equity)
    create_drawdown_analysis(drawdowns, equity)
    create_universe_adaptation(universe)
    create_performance_summary(summary, trades, equity)
    create_trade_analysis(trades)
    
    print("\n" + "="*80)
    print("✓ ALL VISUALIZATIONS COMPLETE")
    print("="*80)
    print("\nGenerated files:")
    print("  1. presentation_equity_curve.png")
    print("  2. presentation_drawdown_analysis.png")
    print("  3. presentation_universe_adaptation.png")
    print("  4. presentation_performance_summary.png")
    print("  5. presentation_trade_analysis.png")
    print("\nThese are high-resolution (300 DPI) images ready for presentation!")

if __name__ == "__main__":
    main()