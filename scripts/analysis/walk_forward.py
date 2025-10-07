"""
Walk-Forward Validation
Tests strategy on rolling time windows
"""

import pandas as pd
import numpy as np
from datetime import datetime

def run_walk_forward_analysis(db, symbols, calculate_vpvma_indicator):
    """
    Walk-forward validation on rolling periods
    
    Returns:
        dict: Performance across different time periods
    """
    print("\n" + "="*80)
    print("WALK-FORWARD VALIDATION")
    print("="*80)
    
    # Define test periods
    periods = [
        {'name': '2020-2021 Bull', 'start': '2020-01-01', 'end': '2021-12-31'},
        {'name': '2021-2022 Peak→Crash', 'start': '2021-01-01', 'end': '2022-12-31'},
        {'name': '2022-2023 Recovery', 'start': '2022-01-01', 'end': '2023-12-31'},
        {'name': '2023-2024 AI Boom', 'start': '2023-01-01', 'end': '2024-12-31'},
        {'name': '2024-2025 Current', 'start': '2024-01-01', 'end': '2025-12-31'}
    ]
    
    INITIAL_CAPITAL = 100000
    COMMISSION = 1
    SLIPPAGE_BPS = 2
    
    period_results = []
    
    for period in periods:
        print(f"\nTesting: {period['name']}...")
        
        period_returns = []
        
        for symbol in symbols:
            try:
                df = db.get_ohlcv_data(symbol)
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                
                # Filter to period
                df_period = df[(df['timestamp'] >= period['start']) & 
                              (df['timestamp'] <= period['end'])].copy()
                
                if len(df_period) < 50:
                    continue
                
                # Calculate VPVMA on full dataset
                open_p, high, low, close, volume = db.get_ohlcv_arrays(symbol)
                result = calculate_vpvma_indicator(high, low, close, open_p, volume)
                
                df['vpvma'] = result['vpvma']
                df['vpvmas'] = result['vpvmas']
                df['signal'] = result['signals']
                df['buy_signal'] = result['buy_signals']
                df['sell_signal'] = result['sell_signals']
                
                # Filter to test period
                df_test = df[(df['timestamp'] >= period['start']) & 
                            (df['timestamp'] <= period['end'])].copy().reset_index(drop=True)
                
                if len(df_test) < 20:
                    continue
                
                # Backtest
                position = 0
                entry_price = 0
                cash = INITIAL_CAPITAL
                equity_curve = [INITIAL_CAPITAL]
                
                for i in range(len(df_test)):
                    row = df_test.iloc[i]
                    
                    if row['buy_signal'] and position == 0:
                        entry_price = row['close'] + row['close'] * (SLIPPAGE_BPS / 10000)
                        position = (cash - COMMISSION) / entry_price
                        cash = 0
                    
                    elif row['sell_signal'] and position > 0:
                        exit_price = row['close'] - row['close'] * (SLIPPAGE_BPS / 10000)
                        cash = exit_price * position - COMMISSION
                        position = 0
                    
                    if position > 0:
                        equity_curve.append(position * row['close'])
                    else:
                        equity_curve.append(cash)
                
                # Calculate return
                final_equity = equity_curve[-1]
                period_return = ((final_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL) * 100
                
                # Buy and hold
                bh_return = ((df_test.iloc[-1]['close'] - df_test.iloc[0]['close']) / 
                            df_test.iloc[0]['close']) * 100
                
                period_returns.append({
                    'symbol': symbol,
                    'return_%': period_return,
                    'bh_return_%': bh_return,
                    'alpha_%': period_return - bh_return
                })
                
            except Exception as e:
                continue
        
        if len(period_returns) > 0:
            returns_df = pd.DataFrame(period_returns)
            profitable_pct = (len(returns_df[returns_df['return_%'] > 0]) / len(returns_df)) * 100
            
            period_results.append({
                'period': period['name'],
                'start': period['start'],
                'end': period['end'],
                'num_stocks': len(returns_df),
                'avg_return_%': returns_df['return_%'].mean(),
                'median_return_%': returns_df['return_%'].median(),
                'profitable_%': profitable_pct,
                'avg_alpha_%': returns_df['alpha_%'].mean(),
                'best_stock': returns_df.loc[returns_df['return_%'].idxmax(), 'symbol'],
                'best_return_%': returns_df['return_%'].max(),
                'worst_stock': returns_df.loc[returns_df['return_%'].idxmin(), 'symbol'],
                'worst_return_%': returns_df['return_%'].min()
            })
            
            print(f"  Avg Return: {returns_df['return_%'].mean():+.1f}%")
            print(f"  Profitable: {profitable_pct:.0f}%")
    
    results_df = pd.DataFrame(period_results)
    
    return {
        'results_df': results_df,
        'consistency_score': len(results_df[results_df['avg_return_%'] > 0]) / len(results_df) * 100 if len(results_df) > 0 else 0
    }