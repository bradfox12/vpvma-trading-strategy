import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.database import Database
from main import calculate_vpvma_indicator
import pandas as pd
import numpy as np
from datetime import datetime

print("="*70)
print("2022 BEAR MARKET TEST - LONG ONLY")
print("The CRITICAL Test: Does VPVMA Protect Capital in Crashes?")
print("="*70)

# Configuration
INITIAL_CAPITAL = 100000
COMMISSION_PER_TRADE = 1
SLIPPAGE_BPS = 2

# 2022 Bear Market Period
START_DATE = '2022-01-01'
END_DATE = '2022-10-31'

db = Database(db_type='postgresql')
symbols = db.list_symbols()

print(f"\nTest Period: {START_DATE} to {END_DATE}")
print(f"Market Regime: Bear Market / Correction")
print(f"SPY Expected: ~-25% decline")
print(f"\nTesting {len(symbols)} symbols...")
print("="*70)

results = []

for symbol in symbols:
    print(f"\n[{symbols.index(symbol)+1}/{len(symbols)}] {symbol}", end=' ')
    
    try:
        # Get full data
        df = db.get_ohlcv_data(symbol)
        
        # Filter to 2022 period
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df_period = df[(df['timestamp'] >= START_DATE) & (df['timestamp'] <= END_DATE)].copy()
        
        if len(df_period) < 50:
            print("✗ Insufficient data for 2022")
            continue
        
        # Need to calculate VPVMA on full dataset (for proper warmup)
        open_p, high, low, close, volume = db.get_ohlcv_arrays(symbol)
        result = calculate_vpvma_indicator(high, low, close, open_p, volume)
        
        df['vpvma'] = result['vpvma']
        df['vpvmas'] = result['vpvmas']
        df['signal'] = result['signals']
        df['buy_signal'] = result['buy_signals']
        df['sell_signal'] = result['sell_signals']
        
        # Filter to test period
        df_test = df[(df['timestamp'] >= START_DATE) & (df['timestamp'] <= END_DATE)].copy().reset_index(drop=True)
        
        # Get starting position from before 2022
        df_before = df[df['timestamp'] < START_DATE].copy()
        
        # Check if we were in a position at start of 2022
        position = 0
        entry_price = 0
        cash = INITIAL_CAPITAL
        
        # Look at last signal before 2022
        if len(df_before) > 0:
            last_signals = df_before[df_before['buy_signal'] == True]
            if len(last_signals) > 0:
                # Check if last buy was after last sell
                last_buy_idx = last_signals.index[-1]
                last_sells = df_before[df_before['sell_signal'] == True]
                
                if len(last_sells) == 0 or last_buy_idx > last_sells.index[-1]:
                    # We entered 2022 with a long position
                    entry_price = df_test.iloc[0]['close']
                    position = (INITIAL_CAPITAL - COMMISSION_PER_TRADE) / entry_price
                    cash = 0
        
        trades = []
        equity_curve = []
        days_in_market = 0
        days_in_cash = 0
        
        # Track when we exited (if we did)
        exit_date = None
        
        # Run backtest on 2022 period
        for i in range(len(df_test)):
            row = df_test.iloc[i]
            
            # Buy signal
            if row['buy_signal'] and position == 0:
                slippage_cost = row['close'] * (SLIPPAGE_BPS / 10000)
                entry_price = row['close'] + slippage_cost
                shares = (cash - COMMISSION_PER_TRADE) / entry_price
                position = shares
                cash = 0
                trades.append({
                    'entry_date': row['timestamp'],
                    'entry_price': entry_price,
                    'shares': shares
                })
            
            # Sell signal
            elif row['sell_signal'] and position > 0:
                slippage_cost = row['close'] * (SLIPPAGE_BPS / 10000)
                exit_price = row['close'] - slippage_cost
                pnl = (exit_price - entry_price) * position
                cash = (exit_price * position) - COMMISSION_PER_TRADE
                
                if exit_date is None:
                    exit_date = row['timestamp']
                
                if len(trades) > 0:
                    trades[-1]['exit_date'] = row['timestamp']
                    trades[-1]['exit_price'] = exit_price
                    trades[-1]['pnl'] = pnl
                    trades[-1]['return_pct'] = ((exit_price - entry_price) / entry_price) * 100
                
                position = 0
                entry_price = 0
            
            # Track exposure
            if position > 0:
                days_in_market += 1
            else:
                days_in_cash += 1
            
            # Calculate equity
            if position > 0:
                current_equity = position * row['close']
            else:
                current_equity = cash
            
            equity_curve.append(current_equity)
        
        # Calculate metrics
        bh_start = df_test.iloc[0]['close']
        bh_end = df_test.iloc[-1]['close']
        bh_return = ((bh_end - bh_start) / bh_start) * 100
        
        final_equity = equity_curve[-1] if equity_curve else INITIAL_CAPITAL
        strategy_return = ((final_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL) * 100
        
        # Max drawdown
        if equity_curve:
            equity_array = np.array([INITIAL_CAPITAL] + equity_curve)
            running_max = np.maximum.accumulate(equity_array)
            drawdown = (equity_array - running_max) / running_max * 100
            max_drawdown = drawdown.min()
        else:
            max_drawdown = 0
        
        # Market exposure
        total_days = days_in_market + days_in_cash
        market_exposure = (days_in_market / total_days * 100) if total_days > 0 else 0
        
        # Calculate buy-and-hold max drawdown
        bh_equity = []
        for price in df_test['close']:
            bh_equity.append(INITIAL_CAPITAL * (price / bh_start))
        bh_equity_array = np.array(bh_equity)
        bh_running_max = np.maximum.accumulate(bh_equity_array)
        bh_drawdown = (bh_equity_array - bh_running_max) / bh_running_max * 100
        bh_max_drawdown = bh_drawdown.min()
        
        results.append({
            'Symbol': symbol,
            'Strategy_Return_%': strategy_return,
            'BuyHold_Return_%': bh_return,
            'Alpha_%': strategy_return - bh_return,
            'Strategy_MaxDD_%': max_drawdown,
            'BuyHold_MaxDD_%': bh_max_drawdown,
            'DD_Protection_%': max_drawdown - bh_max_drawdown,
            'Market_Exp_%': market_exposure,
            'Exit_Date': exit_date.strftime('%Y-%m-%d') if exit_date else 'Never',
            'Trades': len([t for t in trades if 'exit_date' in t])
        })
        
        alpha_symbol = "✓" if strategy_return > bh_return else "✗"
        print(f"{alpha_symbol} Strategy: {strategy_return:+.1f}% | B&H: {bh_return:+.1f}% | Alpha: {strategy_return - bh_return:+.1f}%")
        
    except Exception as e:
        print(f"✗ Error: {e}")

# Results
results_df = pd.DataFrame(results)
results_df = results_df.sort_values('Alpha_%', ascending=False)

print("\n" + "="*70)
print("2022 BEAR MARKET RESULTS")
print("="*70)

pd.set_option('display.max_columns', None)
pd.set_option('display.width', None)
pd.set_option('display.float_format', lambda x: f'{x:.2f}')

print("\n" + results_df.to_string(index=False))

# Critical Analysis
print("\n" + "="*70)
print("CRITICAL ANALYSIS: DID VPVMA PROTECT CAPITAL?")
print("="*70)

beat_bh_count = len(results_df[results_df['Alpha_%'] > 0])
avg_strategy_return = results_df['Strategy_Return_%'].mean()
avg_bh_return = results_df['BuyHold_Return_%'].mean()
avg_strategy_dd = results_df['Strategy_MaxDD_%'].mean()
avg_bh_dd = results_df['BuyHold_MaxDD_%'].mean()

print(f"\nTotal Symbols: {len(results_df)}")
print(f"Beat Buy & Hold: {beat_bh_count}/{len(results_df)} ({beat_bh_count/len(results_df)*100:.1f}%)")

print(f"\n📊 RETURN COMPARISON:")
print(f"  Avg Strategy Return: {avg_strategy_return:+.2f}%")
print(f"  Avg Buy & Hold Return: {avg_bh_return:+.2f}%")
print(f"  Avg Alpha: {avg_strategy_return - avg_bh_return:+.2f}%")

print(f"\n🛡️  DRAWDOWN PROTECTION:")
print(f"  Avg Strategy Max DD: {avg_strategy_dd:.2f}%")
print(f"  Avg Buy & Hold Max DD: {avg_bh_dd:.2f}%")
print(f"  Avg DD Protection: {avg_strategy_dd - avg_bh_dd:+.2f}%")

print(f"\n💼 MARKET EXPOSURE:")
print(f"  Avg Market Exposure: {results_df['Market_Exp_%'].mean():.1f}%")

# Verdict
print("\n" + "="*70)
print("VERDICT:")
print("="*70)

if beat_bh_count >= len(results_df) * 0.75:
    print("\n✅ STRATEGY PASSED THE BEAR MARKET TEST!")
    print(f"   Protected capital on {beat_bh_count}/{len(results_df)} symbols")
    print(f"   Average alpha: {avg_strategy_return - avg_bh_return:+.1f}%")
    print("\n   This is a LEGITIMATE trend-following strategy.")
    print("   It works across market regimes, not just bull markets.")
    
elif beat_bh_count >= len(results_df) * 0.5:
    print("\n⚠️  MIXED RESULTS")
    print(f"   Beat buy-and-hold on {beat_bh_count}/{len(results_df)} symbols")
    print(f"   Works on some symbols, not others in bear markets")
    print("\n   Strategy has some defensive value but not universal.")
    
else:
    print("\n❌ STRATEGY FAILED THE BEAR MARKET TEST")
    print(f"   Only beat buy-and-hold on {beat_bh_count}/{len(results_df)} symbols")
    print(f"   Average alpha: {avg_strategy_return - avg_bh_return:+.1f}%")
    print("\n   This appears to be a BULL MARKET ONLY strategy.")
    print("   Would give back most gains in next bear market.")

# Export
filename = "vpvma_2022_bear_market_test.csv"
results_df.to_csv(filename, index=False)
print(f"\n✓ Results exported to: {filename}")

print("\n" + "="*70)