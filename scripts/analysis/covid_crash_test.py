"""
COVID Crash Test (February-March 2020)
Analyzes strategy behavior during rapid market collapse
"""

import pandas as pd
import numpy as np
from datetime import datetime

def run_covid_crash_test(db, symbols, calculate_vpvma_indicator):
    """
    Test strategy performance during COVID crash (Feb-March 2020)
    
    Returns:
        dict: Results including exit timing, losses, comparisons
    """
    print("\n" + "="*80)
    print("COVID CRASH TEST (February-March 2020)")
    print("="*80)
    
    INITIAL_CAPITAL = 100000
    COMMISSION = 1
    SLIPPAGE_BPS = 2
    
    # COVID crash period
    CRASH_START = '2020-02-01'
    CRASH_BOTTOM = '2020-03-23'
    CRASH_END = '2020-04-30'
    
    results = []
    
    for symbol in symbols:
        try:
            df = db.get_ohlcv_data(symbol)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            
            # Filter to crash period + 1 month before for context
            df_crash = df[(df['timestamp'] >= '2020-01-01') & 
                         (df['timestamp'] <= CRASH_END)].copy()
            
            if len(df_crash) < 50:
                continue
            
            # Calculate VPVMA on full dataset
            open_p, high, low, close, volume = db.get_ohlcv_arrays(symbol)
            result = calculate_vpvma_indicator(high, low, close, open_p, volume)
            
            df['vpvma'] = result['vpvma']
            df['vpvmas'] = result['vpvmas']
            df['signal'] = result['signals']
            df['buy_signal'] = result['buy_signals']
            df['sell_signal'] = result['sell_signals']
            
            # Filter to crash period
            df_test = df[(df['timestamp'] >= '2020-01-01') & 
                        (df['timestamp'] <= CRASH_END)].copy().reset_index(drop=True)
            
            # Check if in position at crash start
            df_before = df[df['timestamp'] < CRASH_START].copy()
            position = 0
            entry_price = 0
            cash = INITIAL_CAPITAL
            
            if len(df_before) > 0:
                last_buys = df_before[df_before['buy_signal'] == True]
                if len(last_buys) > 0:
                    last_buy_idx = last_buys.index[-1]
                    last_sells = df_before[df_before['sell_signal'] == True]
                    
                    if len(last_sells) == 0 or last_buy_idx > last_sells.index[-1]:
                        entry_price = df_test.iloc[0]['close']
                        position = (INITIAL_CAPITAL - COMMISSION) / entry_price
                        cash = 0
            
            equity_curve = []
            exit_date = None
            re_entry_date = None
            
            for i in range(len(df_test)):
                row = df_test.iloc[i]
                
                if row['sell_signal'] and position > 0 and exit_date is None:
                    exit_date = row['timestamp']
                    exit_price = row['close']
                    cash = exit_price * position - COMMISSION
                    position = 0
                
                if row['buy_signal'] and position == 0 and exit_date is not None and re_entry_date is None:
                    re_entry_date = row['timestamp']
                    entry_price = row['close'] + row['close'] * (SLIPPAGE_BPS / 10000)
                    position = (cash - COMMISSION) / entry_price
                    cash = 0
                
                if position > 0:
                    equity = position * row['close']
                else:
                    equity = cash
                
                equity_curve.append({
                    'date': row['timestamp'],
                    'equity': equity,
                    'price': row['close']
                })
            
            # Calculate metrics
            crash_start_idx = df_test[df_test['timestamp'] >= CRASH_START].index[0]
            crash_bottom_idx = df_test[df_test['timestamp'] >= CRASH_BOTTOM].index[0]
            
            start_price = df_test.iloc[crash_start_idx]['close']
            bottom_price = df_test.iloc[crash_bottom_idx]['close']
            end_price = df_test.iloc[-1]['close']
            
            bh_crash_loss = ((bottom_price - start_price) / start_price) * 100
            bh_period_return = ((end_price - start_price) / start_price) * 100
            
            start_equity = equity_curve[crash_start_idx]['equity']
            bottom_equity = equity_curve[crash_bottom_idx]['equity']
            end_equity = equity_curve[-1]['equity']
            
            strategy_crash_loss = ((bottom_equity - start_equity) / start_equity) * 100
            strategy_period_return = ((end_equity - start_equity) / start_equity) * 100
            
            results.append({
                'symbol': symbol,
                'exit_date': exit_date.strftime('%Y-%m-%d') if exit_date else 'Never',
                're_entry_date': re_entry_date.strftime('%Y-%m-%d') if re_entry_date else 'Never',
                'strategy_crash_loss_%': strategy_crash_loss,
                'bh_crash_loss_%': bh_crash_loss,
                'protection_%': strategy_crash_loss - bh_crash_loss,
                'strategy_period_return_%': strategy_period_return,
                'bh_period_return_%': bh_period_return,
                'alpha_%': strategy_period_return - bh_period_return,
                'equity_curve': equity_curve,
                'exited_before_crash': exit_date < pd.to_datetime(CRASH_BOTTOM) if exit_date else False
            })
            
        except Exception as e:
            print(f"  ✗ {symbol}: {e}")
            continue
    
    results_df = pd.DataFrame([{k: v for k, v in r.items() if k != 'equity_curve'} 
                               for r in results])
    
    if len(results_df) > 0:
        print(f"\n✓ Tested {len(results_df)} symbols")
        print(f"  Exited before crash bottom: {results_df['exited_before_crash'].sum()}/{len(results_df)}")
        print(f"  Avg protection: {results_df['protection_%'].mean():.1f}%")
        print(f"  Avg alpha: {results_df['alpha_%'].mean():.1f}%")
    
    return {
        'results_df': results_df,
        'full_results': results,
        'crash_dates': {
            'start': CRASH_START,
            'bottom': CRASH_BOTTOM,
            'end': CRASH_END
        }
    }