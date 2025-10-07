import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.database import Database
from main import calculate_vpvma_indicator
import pandas as pd
import numpy as np
from datetime import datetime

print("="*80)
print("2022 BEAR MARKET TEST - FULL 54-STOCK UNIVERSE")
print("Unbiased Comparison Baseline")
print("="*80)

# Configuration
INITIAL_CAPITAL = 100000
COMMISSION_PER_TRADE = 1
SLIPPAGE_BPS = 2

# 2022 Bear Market Period
START_DATE = '2022-01-01'
END_DATE = '2022-10-31'

db = Database(db_type='postgresql')
all_symbols = db.list_symbols()

print(f"\nTest Period: {START_DATE} to {END_DATE}")
print(f"Testing ALL {len(all_symbols)} stocks in database...")
print("="*80)

results = []

for idx, symbol in enumerate(all_symbols, 1):
    print(f"\r[{idx}/{len(all_symbols)}] Testing {symbol:6}...", end='', flush=True)
    
    try:
        # Get full data
        df = db.get_ohlcv_data(symbol)
        
        # Filter to 2022 period
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df_period = df[(df['timestamp'] >= START_DATE) & (df['timestamp'] <= END_DATE)].copy()
        
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
        df_test = df[(df['timestamp'] >= START_DATE) & (df['timestamp'] <= END_DATE)].copy().reset_index(drop=True)
        
        # Check if we were in a position at start of 2022
        df_before = df[df['timestamp'] < START_DATE].copy()
        
        position = 0
        entry_price = 0
        cash = INITIAL_CAPITAL
        
        # Look at last signal before 2022
        if len(df_before) > 0:
            last_signals = df_before[df_before['buy_signal'] == True]
            if len(last_signals) > 0:
                last_buy_idx = last_signals.index[-1]
                last_sells = df_before[df_before['sell_signal'] == True]
                
                if len(last_sells) == 0 or last_buy_idx > last_sells.index[-1]:
                    entry_price = df_test.iloc[0]['close']
                    position = (INITIAL_CAPITAL - COMMISSION_PER_TRADE) / entry_price
                    cash = 0
        
        trades = []
        equity_curve = []
        days_in_market = 0
        days_in_cash = 0
        exit_date = None
        
        # Run backtest on 2022 period
        for i in range(len(df_test)):
            row = df_test.iloc[i]
            
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
            
            if position > 0:
                days_in_market += 1
            else:
                days_in_cash += 1
            
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
        
        total_days = days_in_market + days_in_cash
        market_exposure = (days_in_market / total_days * 100) if total_days > 0 else 0
        
        # Buy-and-hold max drawdown
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
        
    except Exception as e:
        continue

print("\r" + " " * 80 + "\r", end='')

# Results
results_df = pd.DataFrame(results)

if len(results_df) == 0:
    print("\n❌ No successful backtests!")
    exit(1)

results_df = results_df.sort_values('Alpha_%', ascending=False)

print("\n" + "="*80)
print(f"2022 BEAR MARKET RESULTS - FULL UNIVERSE ({len(results_df)} STOCKS)")
print("="*80)

# Summary statistics
beat_bh_count = len(results_df[results_df['Alpha_%'] > 0])
avg_strategy_return = results_df['Strategy_Return_%'].mean()
median_strategy_return = results_df['Strategy_Return_%'].median()
avg_bh_return = results_df['BuyHold_Return_%'].mean()
avg_alpha = results_df['Alpha_%'].mean()
median_alpha = results_df['Alpha_%'].median()
avg_strategy_dd = results_df['Strategy_MaxDD_%'].mean()
avg_bh_dd = results_df['BuyHold_MaxDD_%'].mean()
avg_market_exp = results_df['Market_Exp_%'].mean()

print(f"\n📊 FULL UNIVERSE SUMMARY:")
print(f"Total Stocks: {len(results_df)}")
print(f"Beat Buy & Hold: {beat_bh_count}/{len(results_df)} ({beat_bh_count/len(results_df)*100:.1f}%)")

print(f"\n💰 RETURNS:")
print(f"  Avg Strategy Return: {avg_strategy_return:+.2f}%")
print(f"  Median Strategy Return: {median_strategy_return:+.2f}%")
print(f"  Avg Buy & Hold Return: {avg_bh_return:+.2f}%")
print(f"  Avg Alpha: {avg_alpha:+.2f}%")
print(f"  Median Alpha: {median_alpha:+.2f}%")

print(f"\n🛡️  DRAWDOWN PROTECTION:")
print(f"  Avg Strategy Max DD: {avg_strategy_dd:.2f}%")
print(f"  Avg Buy & Hold Max DD: {avg_bh_dd:.2f}%")
print(f"  Avg DD Protection: {avg_strategy_dd - avg_bh_dd:+.2f}%")

print(f"\n💼 MARKET EXPOSURE:")
print(f"  Avg Market Exposure: {avg_market_exp:.1f}%")

# Top and bottom performers
print("\n🏆 TOP 10 BY ALPHA:")
print("-" * 80)
for idx, row in results_df.head(10).iterrows():
    print(f"{row['Symbol']:6} | Strategy: {row['Strategy_Return_%']:+7.1f}% | B&H: {row['BuyHold_Return_%']:+7.1f}% | Alpha: {row['Alpha_%']:+7.1f}%")

print("\n📉 BOTTOM 10 BY ALPHA:")
print("-" * 80)
for idx, row in results_df.tail(10).iterrows():
    print(f"{row['Symbol']:6} | Strategy: {row['Strategy_Return_%']:+7.1f}% | B&H: {row['BuyHold_Return_%']:+7.1f}% | Alpha: {row['Alpha_%']:+7.1f}%")

# Export
filename = "vpvma_2022_full_54_universe.csv"
results_df.to_csv(filename, index=False)
print(f"\n✓ Results exported to: {filename}")

print("\n" + "="*80)
print("2022 FULL UNIVERSE TEST COMPLETE")
print("="*80)
print("\nNext: Compare filtered 12 results to these unbiased baseline results")
print("Run comparison analysis to validate filtering effectiveness")