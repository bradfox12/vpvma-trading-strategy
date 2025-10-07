"""
Dynamic Universe Backtest
Simulates monthly rebalancing with VPVMA signals
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from data.database import Database
from main import calculate_vpvma_indicator
from scripts.dynamic_backtest.monthly_trend_selector import get_monthly_universes
from scripts.dynamic_backtest.portfolio_manager import PortfolioManager

def run_dynamic_backtest(db, start_date='2020-01-01', end_date='2025-10-31', 
                         initial_capital=100000, min_score=75, top_n=12):
    """
    Backtest with monthly universe updates and VPVMA signals
    
    Process:
    1. Generate monthly universes (no look-ahead)
    2. For each trading day:
       - Check if month changed (rebalance if needed)
       - Check VPVMA signals on current universe
       - Execute trades
       - Record portfolio state
    3. Analyze results
    
    Args:
        db: Database instance
        start_date: Start date (ISO format)
        end_date: End date (ISO format)
        initial_capital: Starting capital
        min_score: Minimum trend score for inclusion
        top_n: Number of stocks per universe
    
    Returns:
        dict: Complete backtest results
    """
    print("="*80)
    print("DYNAMIC UNIVERSE BACKTEST")
    print("="*80)
    print(f"Period: {start_date} to {end_date}")
    print(f"Initial Capital: ${initial_capital:,.0f}")
    print(f"Universe Size: Top {top_n} stocks (score >= {min_score})")
    print("="*80)
    
    # Step 1: Generate monthly universes
    monthly_universes = get_monthly_universes(db, start_date, end_date, min_score, top_n)
    
    # Step 2: Pre-calculate VPVMA for all possible symbols
    print("\n" + "="*80)
    print("PRE-CALCULATING VPVMA INDICATORS")
    print("="*80)
    
    all_symbols = set()
    for date, data in monthly_universes.items():
        all_symbols.update(data['symbols'])
    
    vpvma_data = {}
    for idx, symbol in enumerate(all_symbols, 1):
        print(f"\r[{idx}/{len(all_symbols)}] Calculating {symbol:6}...", end='', flush=True)
        try:
            df = db.get_ohlcv_data(symbol)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            
            open_p, high, low, close, volume = db.get_ohlcv_arrays(symbol)
            result = calculate_vpvma_indicator(high, low, close, open_p, volume)
            
            df['vpvma'] = result['vpvma']
            df['vpvmas'] = result['vpvmas']
            df['buy_signal'] = result['buy_signals']
            df['sell_signal'] = result['sell_signals']
            
            # Filter to backtest period
            df = df[(df['timestamp'] >= start_date) & (df['timestamp'] <= end_date)].copy()
            df = df.reset_index(drop=True)
            
            vpvma_data[symbol] = df
        except Exception as e:
            print(f"\n  ✗ {symbol}: {e}")
            continue
    
    print("\r" + " "*80 + "\r", end='')
    print(f"✓ Calculated VPVMA for {len(vpvma_data)} symbols")
    
    # Step 3: Run day-by-day simulation
    print("\n" + "="*80)
    print("RUNNING DYNAMIC BACKTEST")
    print("="*80)
    
    portfolio = PortfolioManager(initial_capital=initial_capital)
    
    # Get all trading dates
    sample_df = next(iter(vpvma_data.values()))
    all_dates = sorted(sample_df['timestamp'].unique())
    
    current_month = None
    rebalance_dates = []
    
    for date_idx, current_date in enumerate(all_dates):
        date_str = current_date.strftime('%Y-%m-%d')
        month_key = current_date.strftime('%Y-%m-01')
        
        # Check if we need to rebalance (first trading day of month)
        if month_key != current_month:
            current_month = month_key
            
            # Get new universe for this month
            if month_key in monthly_universes:
                new_universe = monthly_universes[month_key]['symbols']
                
                # Get current prices for rebalancing
                current_prices = {}
                for symbol in set(portfolio.current_universe + new_universe):
                    if symbol in vpvma_data:
                        symbol_df = vpvma_data[symbol]
                        day_data = symbol_df[symbol_df['timestamp'] == current_date]
                        if len(day_data) > 0:
                            current_prices[symbol] = day_data.iloc[0]['close']
                
                # Rebalance
                dropped, added = portfolio.monthly_rebalance(new_universe, date_str, current_prices)
                rebalance_dates.append(date_str)
                
                print(f"\n  {date_str}: Universe = {len(new_universe)} stocks")
                if dropped:
                    print(f"    Dropped: {', '.join(dropped)}")
                if added:
                    print(f"    Added: {', '.join(added)}")
        
        # Check VPVMA signals for current universe
        current_prices = {}
        for symbol in portfolio.current_universe:
            if symbol not in vpvma_data:
                continue
            
            symbol_df = vpvma_data[symbol]
            day_data = symbol_df[symbol_df['timestamp'] == current_date]
            
            if len(day_data) == 0:
                continue
            
            row = day_data.iloc[0]
            current_prices[symbol] = row['close']
            
            # Process signals
            if row['buy_signal']:
                portfolio.process_vpvma_signal(symbol, 'buy', row['close'], date_str)
            elif row['sell_signal']:
                portfolio.process_vpvma_signal(symbol, 'sell', row['close'], date_str)
        
        # Record daily snapshot
        portfolio.record_daily_snapshot(date_str, current_prices)
        
        # Progress indicator
        if date_idx % 50 == 0:
            pct = (date_idx / len(all_dates)) * 100
            print(f"\r  Progress: {pct:.1f}% ({date_idx}/{len(all_dates)} days)", end='', flush=True)
    
    print("\r" + " "*80 + "\r", end='')
    print(f"✓ Completed {len(all_dates)} trading days")
    print(f"✓ Executed {len(rebalance_dates)} monthly rebalances")
    
    # Step 4: Get results
    print("\n" + "="*80)
    print("ANALYZING RESULTS")
    print("="*80)
    
    results = portfolio.get_results_summary()
    
    print(f"\n📊 PERFORMANCE SUMMARY:")
    print(f"  Total Return: {results['total_return_%']:+.2f}%")
    print(f"  Final Equity: ${results['final_equity']:,.0f}")
    print(f"  Max Drawdown: {results['max_drawdown_%']:.2f}%")
    print(f"  Number of Trades: {results['num_trades']}")
    print(f"  Win Rate: {results['win_rate_%']:.1f}%")
    print(f"  Universe Changes: {results['num_universe_changes']}")
    
    # Calculate drawdown durations
    print("\n📉 DRAWDOWN ANALYSIS:")
    history_df = results['history_df']
    equity_curve = history_df['equity'].values
    running_max = np.maximum.accumulate(equity_curve)
    drawdown = (equity_curve - running_max) / running_max
    
    # Find drawdown periods
    underwater = drawdown < -0.01
    drawdown_periods = []
    in_drawdown = False
    start_idx = 0
    
    for i in range(len(underwater)):
        if underwater[i] and not in_drawdown:
            start_idx = i
            in_drawdown = True
        elif not underwater[i] and in_drawdown:
            end_idx = i - 1
            duration_days = end_idx - start_idx + 1
            max_dd = drawdown[start_idx:end_idx+1].min() * 100
            drawdown_periods.append({
                'start_date': history_df.iloc[start_idx]['date'],
                'end_date': history_df.iloc[end_idx]['date'],
                'duration_days': duration_days,
                'max_drawdown_%': max_dd
            })
            in_drawdown = False
    
    if in_drawdown:
        end_idx = len(underwater) - 1
        duration_days = end_idx - start_idx + 1
        max_dd = drawdown[start_idx:end_idx+1].min() * 100
        drawdown_periods.append({
            'start_date': history_df.iloc[start_idx]['date'],
            'end_date': history_df.iloc[end_idx]['date'],
            'duration_days': duration_days,
            'max_drawdown_%': max_dd,
            'ongoing': True
        })
    
    if len(drawdown_periods) > 0:
        dd_df = pd.DataFrame(drawdown_periods)
        print(f"  Total Drawdown Periods: {len(dd_df)}")
        print(f"  Average Duration: {dd_df['duration_days'].mean():.0f} days")
        print(f"  Median Duration: {dd_df['duration_days'].median():.0f} days")
        print(f"  Max Duration: {dd_df['duration_days'].max():.0f} days")
        print(f"  Average Depth: {dd_df['max_drawdown_%'].mean():.1f}%")
        
        results['drawdown_periods'] = dd_df
    
    # Universe change summary
    print("\n🔄 UNIVERSE CHANGES:")
    universe_df = pd.DataFrame(portfolio.universe_changes)
    if len(universe_df) > 0:
        print(f"  Total Changes: {len(universe_df)}")
        print(f"  Avg Stocks Dropped/Month: {universe_df['dropped'].apply(len).mean():.1f}")
        print(f"  Avg Stocks Added/Month: {universe_df['added'].apply(len).mean():.1f}")
        results['universe_changes'] = universe_df
    
    results['monthly_universes'] = monthly_universes
    results['rebalance_dates'] = rebalance_dates
    
    return results