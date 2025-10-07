"""
Drawdown Duration Analysis
Analyzes how long the strategy stays underwater
"""

import pandas as pd
import numpy as np

def calculate_drawdown_periods(equity_curve):
    """
    Calculate all drawdown periods and their durations
    
    Returns:
        list: Drawdown periods with start, end, duration, depth
    """
    equity_array = np.array(equity_curve)
    running_max = np.maximum.accumulate(equity_array)
    drawdown = (equity_array - running_max) / running_max
    
    underwater = drawdown < -0.01  # More than 1% down
    
    periods = []
    in_drawdown = False
    start_idx = 0
    
    for i in range(len(underwater)):
        if underwater[i] and not in_drawdown:
            start_idx = i
            in_drawdown = True
        elif not underwater[i] and in_drawdown:
            end_idx = i - 1
            period_drawdown = drawdown[start_idx:end_idx+1]
            periods.append({
                'start_idx': start_idx,
                'end_idx': end_idx,
                'duration_days': end_idx - start_idx + 1,
                'max_drawdown_%': period_drawdown.min() * 100,
                'start_value': equity_array[start_idx],
                'min_value': equity_array[start_idx:end_idx+1].min(),
                'end_value': equity_array[end_idx]
            })
            in_drawdown = False
    
    # If still in drawdown at end
    if in_drawdown:
        end_idx = len(underwater) - 1
        period_drawdown = drawdown[start_idx:end_idx+1]
        periods.append({
            'start_idx': start_idx,
            'end_idx': end_idx,
            'duration_days': end_idx - start_idx + 1,
            'max_drawdown_%': period_drawdown.min() * 100,
            'start_value': equity_array[start_idx],
            'min_value': equity_array[start_idx:end_idx+1].min(),
            'end_value': equity_array[end_idx],
            'ongoing': True
        })
    
    return periods

def run_drawdown_analysis(db, symbols, calculate_vpvma_indicator):
    """
    Analyze drawdown durations across all symbols
    
    Returns:
        dict: Drawdown statistics and detailed periods
    """
    print("\n" + "="*80)
    print("DRAWDOWN DURATION ANALYSIS")
    print("="*80)
    
    INITIAL_CAPITAL = 100000
    COMMISSION = 1
    SLIPPAGE_BPS = 2
    
    all_drawdown_periods = []
    symbol_results = []
    
    for symbol in symbols:
        try:
            df = db.get_ohlcv_data(symbol)
            
            if len(df) < 300:
                continue
            
            open_p, high, low, close, volume = db.get_ohlcv_arrays(symbol)
            result = calculate_vpvma_indicator(high, low, close, open_p, volume)
            
            df['vpvma'] = result['vpvma']
            df['vpvmas'] = result['vpvmas']
            df['signal'] = result['signals']
            df['buy_signal'] = result['buy_signals']
            df['sell_signal'] = result['sell_signals']
            
            df_valid = df[35:].copy().reset_index(drop=True)
            
            # Run backtest
            position = 0
            entry_price = 0
            equity_curve = [INITIAL_CAPITAL]
            cash = INITIAL_CAPITAL
            
            for i in range(len(df_valid)):
                row = df_valid.iloc[i]
                
                if row['buy_signal'] and position == 0:
                    entry_price = row['close'] + row['close'] * (SLIPPAGE_BPS / 10000)
                    position = (cash - COMMISSION) / entry_price
                    cash = 0
                
                elif row['sell_signal'] and position > 0:
                    exit_price = row['close'] - row['close'] * (SLIPPAGE_BPS / 10000)
                    cash = exit_price * position - COMMISSION
                    position = 0
                
                if position > 0:
                    current_equity = position * row['close']
                else:
                    current_equity = cash
                
                equity_curve.append(current_equity)
            
            # Analyze drawdowns
            periods = calculate_drawdown_periods(equity_curve)
            
            for period in periods:
                period['symbol'] = symbol
                all_drawdown_periods.append(period)
            
            if len(periods) > 0:
                avg_duration = np.mean([p['duration_days'] for p in periods])
                max_duration = max([p['duration_days'] for p in periods])
                avg_depth = np.mean([p['max_drawdown_%'] for p in periods])
                max_depth = min([p['max_drawdown_%'] for p in periods])
                
                symbol_results.append({
                    'symbol': symbol,
                    'num_drawdowns': len(periods),
                    'avg_duration_days': avg_duration,
                    'max_duration_days': max_duration,
                    'avg_depth_%': avg_depth,
                    'max_depth_%': max_depth
                })
            
        except Exception as e:
            continue
    
    results_df = pd.DataFrame(symbol_results)
    periods_df = pd.DataFrame(all_drawdown_periods)
    
    if len(results_df) > 0:
        print(f"\n✓ Analyzed {len(results_df)} symbols")
        print(f"  Total drawdown periods: {len(periods_df)}")
        print(f"  Avg duration: {results_df['avg_duration_days'].mean():.0f} days")
        print(f"  Max duration: {results_df['max_duration_days'].max():.0f} days")
        print(f"  Avg depth: {results_df['avg_depth_%'].mean():.1f}%")
    
    return {
        'summary_df': results_df,
        'periods_df': periods_df,
        'overall_stats': {
            'total_periods': len(periods_df),
            'avg_duration': periods_df['duration_days'].mean() if len(periods_df) > 0 else 0,
            'median_duration': periods_df['duration_days'].median() if len(periods_df) > 0 else 0,
            'max_duration': periods_df['duration_days'].max() if len(periods_df) > 0 else 0,
            'avg_depth': periods_df['max_drawdown_%'].mean() if len(periods_df) > 0 else 0
        }
    }