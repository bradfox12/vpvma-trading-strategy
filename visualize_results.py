"""
20-Year VPVMA Strategy Performance Visualization Suite
Creates publication-quality charts for LinkedIn and portfolio presentation

Usage:
    1. Run your 20-year backtest and save results
    2. Run this script: python visualize_20year_results.py
    3. Charts saved to ./charts/ directory
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.gridspec import GridSpec
import seaborn as sns
from datetime import datetime
from data.database import Database
from backtest import run_backtest

# Set style
plt.style.use('seaborn-v0_8-darkgrid')
sns.set_palette("husl")
plt.rcParams['figure.figsize'] = (14, 8)
plt.rcParams['font.size'] = 10
plt.rcParams['axes.labelsize'] = 11
plt.rcParams['axes.titlesize'] = 13
plt.rcParams['xtick.labelsize'] = 9
plt.rcParams['ytick.labelsize'] = 9

# Create output directory
OUTPUT_DIR = Path('./charts')
OUTPUT_DIR.mkdir(exist_ok=True)


def get_spy_benchmark(db, start_date, end_date):
    """Get SPY buy-and-hold performance for comparison"""
    spy_data = db.get_ohlcv_data('SPY', start_date=start_date, end_date=end_date)
    
    initial_price = spy_data['close'].iloc[0]
    spy_data['equity'] = (spy_data['close'] / initial_price) * 100000
    spy_data['returns'] = spy_data['close'].pct_change()
    
    # Calculate SPY metrics
    total_return = (spy_data['close'].iloc[-1] / spy_data['close'].iloc[0] - 1) * 100
    years = len(spy_data) / 252
    cagr = ((spy_data['close'].iloc[-1] / spy_data['close'].iloc[0]) ** (1/years) - 1) * 100
    
    spy_data['cummax'] = spy_data['close'].cummax()
    spy_data['drawdown'] = (spy_data['close'] / spy_data['cummax'] - 1) * 100
    max_dd = spy_data['drawdown'].min()
    
    mean_return = spy_data['returns'].mean()
    std_return = spy_data['returns'].std()
    sharpe = (mean_return / std_return * np.sqrt(252)) if std_return > 0 else 0
    
    return {
        'data': spy_data,
        'total_return': total_return,
        'cagr': cagr,
        'sharpe': sharpe,
        'max_dd': max_dd
    }


def plot_equity_curve(results, spy_benchmark, save_path):
    """
    Chart 1: Equity curve comparison
    Shows your strategy vs SPY buy-and-hold over 20 years
    """
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), height_ratios=[3, 1])
    
    # Main equity curve
    df_history = results['history']
    spy_data = spy_benchmark['data']
    
    # Plot both equity curves
    ax1.plot(df_history['date'], df_history['equity'], 
             label='VPVMA + FastExit+SPY200', linewidth=2, color='#2E86AB')
    ax1.plot(spy_data['timestamp'], spy_data['equity'], 
             label='SPY Buy & Hold', linewidth=2, color='#A23B72', alpha=0.7)
    
    # Highlight bear market periods
    bear_periods = [
        ('2008 Crisis', '2008-09-01', '2009-03-31', '#FF6B6B'),
        ('2020 COVID', '2020-02-01', '2020-04-30', '#FFB347'),
        ('2022 Bear', '2022-01-01', '2022-12-31', '#DDA15E')
    ]
    
    for name, start, end, color in bear_periods:
        ax1.axvspan(pd.Timestamp(start), pd.Timestamp(end), 
                    alpha=0.15, color=color, label=f'{name}')
    
    ax1.set_ylabel('Portfolio Value ($)', fontsize=12, fontweight='bold')
    ax1.set_title('20-Year Performance: VPVMA Strategy vs SPY Buy & Hold (2005-2025)', 
                  fontsize=14, fontweight='bold', pad=20)
    ax1.legend(loc='upper left', fontsize=10)
    ax1.grid(True, alpha=0.3)
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}'))
    
    # Add performance stats as text box
    stats_text = f"""Strategy Performance:
    Final Value: ${df_history['equity'].iloc[-1]:,.0f}
    CAGR: {results['metrics']['cagr']:.2f}%
    Sharpe: {results['metrics']['sharpe']:.2f}
    Max DD: {results['metrics']['max_dd']:.2f}%
    
    SPY Benchmark:
    Final Value: ${spy_data['equity'].iloc[-1]:,.0f}
    CAGR: {spy_benchmark['cagr']:.2f}%
    Sharpe: {spy_benchmark['sharpe']:.2f}
    Max DD: {spy_benchmark['max_dd']:.2f}%"""
    
    ax1.text(0.02, 0.98, stats_text, transform=ax1.transAxes,
             verticalalignment='top', bbox=dict(boxstyle='round', 
             facecolor='wheat', alpha=0.8), fontsize=9, family='monospace')
    
    # Number of positions over time
    ax2.plot(df_history['date'], df_history['num_positions'], 
             color='#2E86AB', linewidth=1.5)
    ax2.fill_between(df_history['date'], 0, df_history['num_positions'], 
                      alpha=0.3, color='#2E86AB')
    ax2.axhline(y=20, color='red', linestyle='--', alpha=0.5, label='Max Positions')
    ax2.set_ylabel('Active Positions', fontsize=11, fontweight='bold')
    ax2.set_xlabel('Date', fontsize=11, fontweight='bold')
    ax2.legend(loc='upper right', fontsize=9)
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(save_path, dpi=300, bbox_inches='tight')
    print(f"✓ Saved: {save_path}")
    plt.close()


def plot_drawdown_comparison(results, spy_benchmark, save_path):
    """
    Chart 2: Drawdown comparison
    Shows how your strategy protects capital vs SPY
    """
    fig, ax = plt.subplots(figsize=(14, 8))
    
    df_history = results['history']
    spy_data = spy_benchmark['data']
    
    # Plot drawdowns
    ax.fill_between(df_history['date'], df_history['drawdown'], 0,
                     alpha=0.4, color='#2E86AB', label='VPVMA Strategy')
    ax.fill_between(spy_data['timestamp'], spy_data['drawdown'], 0,
                     alpha=0.4, color='#A23B72', label='SPY Buy & Hold')
    
    ax.plot(df_history['date'], df_history['drawdown'], 
            color='#2E86AB', linewidth=1.5)
    ax.plot(spy_data['timestamp'], spy_data['drawdown'], 
            color='#A23B72', linewidth=1.5)
    
    # Highlight major drawdown periods
    strategy_dd = df_history['drawdown'].min()
    spy_dd = spy_data['drawdown'].min()
    
    ax.axhline(y=strategy_dd, color='#2E86AB', linestyle='--', alpha=0.7,
               label=f'Strategy Max DD: {strategy_dd:.1f}%')
    ax.axhline(y=spy_dd, color='#A23B72', linestyle='--', alpha=0.7,
               label=f'SPY Max DD: {spy_dd:.1f}%')
    
    ax.set_ylabel('Drawdown (%)', fontsize=12, fontweight='bold')
    ax.set_xlabel('Date', fontsize=12, fontweight='bold')
    ax.set_title('Drawdown Comparison: Capital Preservation During Bear Markets', 
                 fontsize=14, fontweight='bold', pad=20)
    ax.legend(loc='lower left', fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{x:.0f}%'))
    
    plt.tight_layout()
    plt.savefig(save_path, dpi=300, bbox_inches='tight')
    print(f"✓ Saved: {save_path}")
    plt.close()


def plot_rolling_metrics(results, save_path):
    """
    Chart 3: Rolling performance metrics
    Shows Sharpe ratio and returns over time
    """
    fig = plt.figure(figsize=(14, 10))
    gs = GridSpec(3, 1, height_ratios=[1.5, 1, 1])
    
    df_history = results['history'].copy()
    
    # Calculate rolling metrics
    window = 252  # 1 year
    df_history['rolling_sharpe'] = (
        df_history['returns'].rolling(window).mean() / 
        df_history['returns'].rolling(window).std() * np.sqrt(252)
    )
    df_history['rolling_return'] = (
        df_history['equity'].pct_change(window) * 100
    )
    
    # Rolling Sharpe
    ax1 = fig.add_subplot(gs[0])
    ax1.plot(df_history['date'], df_history['rolling_sharpe'], 
             color='#2E86AB', linewidth=2)
    ax1.axhline(y=1.0, color='green', linestyle='--', alpha=0.5, 
                label='Sharpe = 1.0 (Excellent)')
    ax1.axhline(y=0, color='red', linestyle='--', alpha=0.5)
    ax1.fill_between(df_history['date'], 0, df_history['rolling_sharpe'],
                      where=(df_history['rolling_sharpe'] > 0),
                      alpha=0.3, color='green', label='Positive Sharpe')
    ax1.fill_between(df_history['date'], 0, df_history['rolling_sharpe'],
                      where=(df_history['rolling_sharpe'] < 0),
                      alpha=0.3, color='red', label='Negative Sharpe')
    ax1.set_ylabel('Rolling Sharpe (1Y)', fontsize=11, fontweight='bold')
    ax1.set_title('Rolling Performance Metrics (1-Year Window)', 
                  fontsize=14, fontweight='bold', pad=20)
    ax1.legend(loc='upper left', fontsize=9)
    ax1.grid(True, alpha=0.3)
    
    # Rolling Returns
    ax2 = fig.add_subplot(gs[1])
    colors = ['green' if x > 0 else 'red' for x in df_history['rolling_return']]
    ax2.bar(df_history['date'], df_history['rolling_return'], 
            color=colors, alpha=0.6, width=1)
    ax2.axhline(y=0, color='black', linewidth=1)
    ax2.set_ylabel('Rolling Return (%)', fontsize=11, fontweight='bold')
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{x:.0f}%'))
    ax2.grid(True, alpha=0.3)
    
    # Protection activation
    ax3 = fig.add_subplot(gs[2])
    protection_periods = df_history[df_history['protection_active'] == True]
    ax3.scatter(protection_periods['date'], 
                [1] * len(protection_periods),
                color='#FF6B6B', alpha=0.6, s=1, label='Protection Active')
    ax3.set_ylim(0, 2)
    ax3.set_ylabel('FastExit', fontsize=11, fontweight='bold')
    ax3.set_xlabel('Date', fontsize=11, fontweight='bold')
    ax3.set_yticks([])
    ax3.legend(loc='upper right', fontsize=9)
    ax3.grid(True, alpha=0.3, axis='x')
    
    plt.tight_layout()
    plt.savefig(save_path, dpi=300, bbox_inches='tight')
    print(f"✓ Saved: {save_path}")
    plt.close()


def plot_annual_performance(results, spy_benchmark, save_path):
    """
    Chart 4: Annual returns comparison
    Bar chart showing year-by-year performance
    """
    df_history = results['history'].copy()
    spy_data = spy_benchmark['data'].copy()
    
    # Calculate annual returns
    df_history['year'] = df_history['date'].dt.year
    spy_data['year'] = spy_data['timestamp'].dt.year
    
    strategy_annual = df_history.groupby('year').apply(
        lambda x: (x['equity'].iloc[-1] / x['equity'].iloc[0] - 1) * 100
    ).reset_index(name='return')
    
    spy_annual = spy_data.groupby('year').apply(
        lambda x: (x['close'].iloc[-1] / x['close'].iloc[0] - 1) * 100
    ).reset_index(name='return')
    
    # Create comparison dataframe
    comparison = pd.merge(strategy_annual, spy_annual, 
                          on='year', suffixes=('_strategy', '_spy'))
    
    fig, ax = plt.subplots(figsize=(14, 8))
    
    x = np.arange(len(comparison))
    width = 0.35
    
    bars1 = ax.bar(x - width/2, comparison['return_strategy'], width,
                   label='VPVMA Strategy', color='#2E86AB', alpha=0.8)
    bars2 = ax.bar(x + width/2, comparison['return_spy'], width,
                   label='SPY Buy & Hold', color='#A23B72', alpha=0.8)
    
    # Add value labels on bars
    for bars in [bars1, bars2]:
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                    f'{height:.1f}%', ha='center', va='bottom' if height > 0 else 'top',
                    fontsize=8, rotation=0)
    
    ax.axhline(y=0, color='black', linewidth=1)
    ax.set_ylabel('Annual Return (%)', fontsize=12, fontweight='bold')
    ax.set_xlabel('Year', fontsize=12, fontweight='bold')
    ax.set_title('Year-by-Year Performance Comparison (2005-2025)', 
                 fontsize=14, fontweight='bold', pad=20)
    ax.set_xticks(x)
    ax.set_xticklabels(comparison['year'], rotation=45)
    ax.legend(loc='upper left', fontsize=10)
    ax.grid(True, alpha=0.3, axis='y')
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{x:.0f}%'))
    
    # Add summary stats
    strategy_wins = (comparison['return_strategy'] > 0).sum()
    spy_wins = (comparison['return_spy'] > 0).sum()
    outperform = (comparison['return_strategy'] > comparison['return_spy']).sum()
    
    stats_text = f"""Performance Summary:
    Strategy Positive Years: {strategy_wins}/{len(comparison)}
    SPY Positive Years: {spy_wins}/{len(comparison)}
    Years Outperformed SPY: {outperform}/{len(comparison)}
    
    Avg Strategy Return: {comparison['return_strategy'].mean():.1f}%
    Avg SPY Return: {comparison['return_spy'].mean():.1f}%"""
    
    ax.text(0.98, 0.98, stats_text, transform=ax.transAxes,
            verticalalignment='top', horizontalalignment='right',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8),
            fontsize=9, family='monospace')
    
    plt.tight_layout()
    plt.savefig(save_path, dpi=300, bbox_inches='tight')
    print(f"✓ Saved: {save_path}")
    plt.close()


def plot_monthly_returns_heatmap(results, save_path):
    """
    Chart 5: Monthly returns heatmap
    Shows consistency of returns across months/years
    """
    df_history = results['history'].copy()
    
    # Calculate monthly returns
    df_history['year'] = df_history['date'].dt.year
    df_history['month'] = df_history['date'].dt.month
    
    monthly_returns = df_history.groupby(['year', 'month']).apply(
        lambda x: (x['equity'].iloc[-1] / x['equity'].iloc[0] - 1) * 100
    ).reset_index(name='return')
    
    # Pivot for heatmap
    pivot = monthly_returns.pivot(index='year', columns='month', values='return')
    
    fig, ax = plt.subplots(figsize=(14, 10))
    
    # Create heatmap
    sns.heatmap(pivot, annot=True, fmt='.1f', cmap='RdYlGn', center=0,
                cbar_kws={'label': 'Monthly Return (%)'}, ax=ax,
                linewidths=0.5, linecolor='gray')
    
    ax.set_xlabel('Month', fontsize=12, fontweight='bold')
    ax.set_ylabel('Year', fontsize=12, fontweight='bold')
    ax.set_title('Monthly Returns Heatmap (2005-2025)', 
                 fontsize=14, fontweight='bold', pad=20)
    
    month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                   'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    ax.set_xticklabels(month_names, rotation=0)
    
    plt.tight_layout()
    plt.savefig(save_path, dpi=300, bbox_inches='tight')
    print(f"✓ Saved: {save_path}")
    plt.close()


def plot_trade_analysis(results, save_path):
    """
    Chart 6: Trade analysis
    Distribution of returns, win rate, hold times
    """
    df_trades = results['trades']
    sell_trades = df_trades[df_trades['action'] == 'SELL'].copy()
    
    fig = plt.figure(figsize=(14, 10))
    gs = GridSpec(2, 2)
    
    # P&L Distribution
    ax1 = fig.add_subplot(gs[0, 0])
    sell_trades['pnl'].hist(bins=50, ax=ax1, color='#2E86AB', alpha=0.7, edgecolor='black')
    ax1.axvline(x=0, color='red', linestyle='--', linewidth=2)
    ax1.axvline(x=sell_trades['pnl'].median(), color='green', 
                linestyle='--', linewidth=2, label=f'Median: ${sell_trades["pnl"].median():.0f}')
    ax1.set_xlabel('P&L per Trade ($)', fontsize=11, fontweight='bold')
    ax1.set_ylabel('Frequency', fontsize=11, fontweight='bold')
    ax1.set_title('Trade P&L Distribution', fontsize=12, fontweight='bold')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # Win/Loss breakdown
    ax2 = fig.add_subplot(gs[0, 1])
    wins = len(sell_trades[sell_trades['pnl'] > 0])
    losses = len(sell_trades[sell_trades['pnl'] <= 0])
    ax2.pie([wins, losses], labels=['Wins', 'Losses'], autopct='%1.1f%%',
            colors=['#2ECC71', '#E74C3C'], startangle=90)
    ax2.set_title(f'Win Rate: {results["metrics"]["win_rate"]:.1f}%', 
                  fontsize=12, fontweight='bold')
    
    # Hold time distribution
    ax3 = fig.add_subplot(gs[1, 0])
    sell_trades['hold_days'].hist(bins=30, ax=ax3, color='#2E86AB', 
                                   alpha=0.7, edgecolor='black')
    ax3.axvline(x=sell_trades['hold_days'].median(), color='red', 
                linestyle='--', linewidth=2, 
                label=f'Median: {sell_trades["hold_days"].median():.0f} days')
    ax3.set_xlabel('Hold Period (days)', fontsize=11, fontweight='bold')
    ax3.set_ylabel('Frequency', fontsize=11, fontweight='bold')
    ax3.set_title('Hold Time Distribution', fontsize=12, fontweight='bold')
    ax3.legend()
    ax3.grid(True, alpha=0.3)
    
    # Protection effectiveness
    ax4 = fig.add_subplot(gs[1, 1])
    fast_exit_trades = sell_trades[sell_trades['fast_exit'] == True]
    normal_trades = sell_trades[sell_trades['fast_exit'] == False]
    
    data = [
        fast_exit_trades['pnl'].mean() if len(fast_exit_trades) > 0 else 0,
        normal_trades['pnl'].mean() if len(normal_trades) > 0 else 0
    ]
    labels = [f'FastExit\n(n={len(fast_exit_trades)})', 
              f'Normal\n(n={len(normal_trades)})']
    colors = ['#FF6B6B', '#2E86AB']
    
    bars = ax4.bar(labels, data, color=colors, alpha=0.7, edgecolor='black')
    ax4.axhline(y=0, color='black', linewidth=1)
    ax4.set_ylabel('Average P&L ($)', fontsize=11, fontweight='bold')
    ax4.set_title('Exit Type Performance', fontsize=12, fontweight='bold')
    ax4.grid(True, alpha=0.3, axis='y')
    
    # Add value labels
    for bar in bars:
        height = bar.get_height()
        ax4.text(bar.get_x() + bar.get_width()/2., height,
                f'${height:.0f}', ha='center', 
                va='bottom' if height > 0 else 'top', fontsize=10)
    
    plt.suptitle('Trade Analysis: 20-Year Performance', 
                 fontsize=14, fontweight='bold', y=0.995)
    plt.tight_layout()
    plt.savefig(save_path, dpi=300, bbox_inches='tight')
    print(f"✓ Saved: {save_path}")
    plt.close()


def create_summary_dashboard(results, spy_benchmark, save_path):
    """
    Chart 7: Summary dashboard
    Single-page overview for LinkedIn
    """
    fig = plt.figure(figsize=(16, 10))
    gs = GridSpec(3, 3, hspace=0.4, wspace=0.3)
    
    df_history = results['history']
    spy_data = spy_benchmark['data']
    metrics = results['metrics']
    
    # Main equity curve
    ax1 = fig.add_subplot(gs[0:2, :])
    ax1.plot(df_history['date'], df_history['equity'], 
             label='VPVMA Strategy', linewidth=2.5, color='#2E86AB')
    ax1.plot(spy_data['timestamp'], spy_data['equity'], 
             label='SPY Benchmark', linewidth=2, color='#A23B72', alpha=0.7)
    ax1.set_ylabel('Portfolio Value ($)', fontsize=12, fontweight='bold')
    ax1.set_title('20-Year Performance Summary (2005-2025)', 
                  fontsize=16, fontweight='bold', pad=20)
    ax1.legend(loc='upper left', fontsize=11)
    ax1.grid(True, alpha=0.3)
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}'))
    
    # Key metrics boxes
    metrics_data = [
        ('CAGR', f"{metrics['cagr']:.1f}%", f"{spy_benchmark['cagr']:.1f}%"),
        ('Sharpe Ratio', f"{metrics['sharpe']:.2f}", f"{spy_benchmark['sharpe']:.2f}"),
        ('Max Drawdown', f"{metrics['max_dd']:.1f}%", f"{spy_benchmark['max_dd']:.1f}%"),
        ('Win Rate', f"{metrics['win_rate']:.1f}%", "N/A"),
        ('Final Value', f"${df_history['equity'].iloc[-1]:,.0f}", 
         f"${spy_data['equity'].iloc[-1]:,.0f}"),
        ('Total Trades', f"{len(results['trades'])}", "N/A")
    ]
    
    for idx, (metric, strategy_val, spy_val) in enumerate(metrics_data):
        ax = fig.add_subplot(gs[2, idx % 3])
        
        # Color code based on which is better
        strategy_color = '#2ECC71'  # Green
        spy_color = '#E74C3C'  # Red
        
        ax.text(0.5, 0.7, metric, ha='center', va='center', 
                fontsize=12, fontweight='bold', transform=ax.transAxes)
        ax.text(0.5, 0.4, strategy_val, ha='center', va='center',
                fontsize=16, fontweight='bold', color=strategy_color,
                transform=ax.transAxes)
        ax.text(0.5, 0.15, f'vs SPY: {spy_val}', ha='center', va='center',
                fontsize=9, color='gray', transform=ax.transAxes)
        
        ax.axis('off')
        ax.add_patch(plt.Rectangle((0.05, 0.05), 0.9, 0.9, 
                                    fill=False, edgecolor='gray', 
                                    linewidth=2, transform=ax.transAxes))
    
    plt.suptitle('VPVMA + FastExit+SPY200: Quantitative Momentum Strategy', 
                 fontsize=18, fontweight='bold', y=0.995)
    
    plt.savefig(save_path, dpi=300, bbox_inches='tight')
    print(f"✓ Saved: {save_path}")
    plt.close()


def generate_all_charts():
    """
    Main function: Run 20-year backtest and create all visualizations
    """
    print("=" * 80)
    print("20-YEAR VPVMA STRATEGY VISUALIZATION SUITE")
    print("=" * 80)
    print()
    
    # Initialize database
    db = Database(db_type='postgresql')
    
    # Load universe
    symbols_query = """
        SELECT DISTINCT symbol 
        FROM ohlcv_data 
        WHERE symbol != 'SPY'
        ORDER BY symbol
    """
    symbols_df = pd.read_sql(symbols_query, db.engine)
    symbols = symbols_df['symbol'].tolist()
    
    # Run 20-year backtest
    print("Running 20-year backtest (2005-2025)...")
    print("This will take approximately 30-45 minutes...")
    print()
    
    results = run_backtest(
        db=db,
        symbols=symbols,
        start_date='2005-01-01',
        end_date='2025-10-31',
        initial_capital=100000
    )
    
    print()
    print("=" * 80)
    print("Backtest complete! Generating visualizations...")
    print("=" * 80)
    print()
    
    # Get SPY benchmark
    print("Loading SPY benchmark data...")
    spy_benchmark = get_spy_benchmark(db, '2005-01-01', '2025-10-31')
    print("✓ SPY benchmark loaded")
    print()
    
    # Generate all charts
    print("Creating visualization suite...")
    print()
    
    plot_equity_curve(results, spy_benchmark, 
                     OUTPUT_DIR / '1_equity_curve.png')
    
    plot_drawdown_comparison(results, spy_benchmark,
                            OUTPUT_DIR / '2_drawdown_comparison.png')
    
    plot_rolling_metrics(results,
                        OUTPUT_DIR / '3_rolling_metrics.png')
    
    plot_annual_performance(results, spy_benchmark,
                           OUTPUT_DIR / '4_annual_returns.png')
    
    plot_monthly_returns_heatmap(results,
                                OUTPUT_DIR / '5_monthly_heatmap.png')
    
    plot_trade_analysis(results,
                       OUTPUT_DIR / '6_trade_analysis.png')
    
    create_summary_dashboard(results, spy_benchmark,
                            OUTPUT_DIR / '7_summary_dashboard.png')
    
    print()
    print("=" * 80)
    print("✅ ALL VISUALIZATIONS COMPLETE!")
    print("=" * 80)
    print()
    print(f"Charts saved to: {OUTPUT_DIR.absolute()}")
    print()
    print("Charts generated:")
    print("  1. Equity Curve (Strategy vs SPY)")
    print("  2. Drawdown Comparison")
    print("  3. Rolling Performance Metrics")
    print("  4. Annual Returns Comparison")
    print("  5. Monthly Returns Heatmap")
    print("  6. Trade Analysis")
    print("  7. Summary Dashboard (LinkedIn-ready)")
    print()
    print("Recommended for LinkedIn: Chart #7 (Summary Dashboard)")
    print("=" * 80)


if __name__ == "__main__":
    generate_all_charts()