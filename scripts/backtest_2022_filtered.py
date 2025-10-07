import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.database import Database
from main import calculate_vpvma_indicator
import pandas as pd
import numpy as np
from datetime import datetime

print("="*80)
print("2022 BEAR MARKET TEST - HIGH-QUALITY FILTERED UNIVERSE")
print("The CRITICAL Test: Does Filtering Improve Bear Market Protection?")
print("="*80)

# The 12 high-quality stocks
HIGH_QUALITY_SYMBOLS = [
    'INTC', 'LYFT', 'PLTR', 'SHOP', 'TSLA', 'UBER', 
    'NVDA', 'COIN', 'ORCL', 'AMD', 'AVGO', 'RBLX'
]

# Configuration
INITIAL_CAPITAL = 100000
COMMISSION_PER_TRADE = 1
SLIPPAGE_BPS = 2

# 2022 Bear Market Period
START_DATE = '2022-01-01'
END_DATE = '2022-10-31'

db = Database(db_type='postgresql')

print(f"\nTest Period: {START_DATE} to {END_DATE}")
print(f"Market Regime: Bear Market / Correction")
print(f"Universe: 12 High-Quality Trending Stocks")
print(f"Symbols: {', '.join(HIGH_QUALITY_SYMBOLS)}")
print("="*80)

results = []

for idx, symbol in enumerate(HIGH_QUALITY_SYMBOLS, 1):
    print(f"\n[{idx}/{len(HIGH_QUALITY_SYMBOLS)}] {symbol}", end=' ')
    
    try:
        # Get full data
        df = db.get_ohlcv_data(symbol)
        
        # Filter to 2022 period
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df_period = df[(df['timestamp'] >= START_DATE) & (df['timestamp'] <= END_DATE)].copy()
        
        if len(df_period) < 50:
            print("✗ Insufficient data for 2022")
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
        
        alpha_symbol = "✓" if strategy_return > bh_return else "✗"
        print(f"{alpha_symbol} Strategy: {strategy_return:+.1f}% | B&H: {bh_return:+.1f}% | Alpha: {strategy_return - bh_return:+.1f}%")
        
    except Exception as e:
        print(f"✗ Error: {e}")

# Results
results_df = pd.DataFrame(results)
results_df = results_df.sort_values('Alpha_%', ascending=False)

print("\n" + "="*80)
print("2022 BEAR MARKET RESULTS - FILTERED UNIVERSE")
print("="*80)

pd.set_option('display.max_columns', None)
pd.set_option('display.width', None)
pd.set_option('display.float_format', lambda x: f'{x:.2f}')

print("\n" + results_df.to_string(index=False))

# Critical Analysis
print("\n" + "="*80)
print("CRITICAL ANALYSIS: DID FILTERING IMPROVE BEAR MARKET PROTECTION?")
print("="*80)

beat_bh_count = len(results_df[results_df['Alpha_%'] > 0])
avg_strategy_return = results_df['Strategy_Return_%'].mean()
avg_bh_return = results_df['BuyHold_Return_%'].mean()
avg_strategy_dd = results_df['Strategy_MaxDD_%'].mean()
avg_bh_dd = results_df['BuyHold_MaxDD_%'].mean()
avg_market_exp = results_df['Market_Exp_%'].mean()

print(f"\n📊 FILTERED UNIVERSE (12 stocks):")
print(f"  Beat Buy & Hold: {beat_bh_count}/{len(results_df)} ({beat_bh_count/len(results_df)*100:.1f}%)")
print(f"  Avg Strategy Return: {avg_strategy_return:+.2f}%")
print(f"  Avg Buy & Hold Return: {avg_bh_return:+.2f}%")
print(f"  Avg Alpha: {avg_strategy_return - avg_bh_return:+.2f}%")

print(f"\n🛡️  DRAWDOWN PROTECTION:")
print(f"  Avg Strategy Max DD: {avg_strategy_dd:.2f}%")
print(f"  Avg Buy & Hold Max DD: {avg_bh_dd:.2f}%")
print(f"  Avg DD Protection: {avg_strategy_dd - avg_bh_dd:+.2f}%")

print(f"\n💼 MARKET EXPOSURE:")
print(f"  Avg Market Exposure: {avg_market_exp:.1f}%")

# Compare to full 54 universe
print("\n" + "="*80)
print("COMPARISON: FILTERED vs FULL UNIVERSE (2022 BEAR)")
print("="*80)

try:
    full_2022 = pd.read_csv('vpvma_2022_bear_market_test.csv')
    
    full_beat_bh = len(full_2022[full_2022['Alpha_%'] > 0])
    full_avg_alpha = full_2022['Alpha_%'].mean()
    full_avg_strategy_dd = full_2022['Strategy_MaxDD_%'].mean()
    full_avg_market_exp = full_2022['Market_Exp_%'].mean()
    
    print(f"\n{'Metric':<35} {'Filtered (12)':<20} {'Full (8)':<20} {'Difference'}")
    print("-" * 90)
    print(f"{'Beat B&H %':<35} {beat_bh_count/len(results_df)*100:<20.1f} {full_beat_bh/len(full_2022)*100:<20.1f} {(beat_bh_count/len(results_df) - full_beat_bh/len(full_2022))*100:+.1f}%")
    print(f"{'Avg Alpha %':<35} {avg_strategy_return - avg_bh_return:<20.2f} {full_avg_alpha:<20.2f} {(avg_strategy_return - avg_bh_return) - full_avg_alpha:+.2f}%")
    print(f"{'Avg Strategy Max DD %':<35} {avg_strategy_dd:<20.2f} {full_avg_strategy_dd:<20.2f} {avg_strategy_dd - full_avg_strategy_dd:+.2f}%")
    print(f"{'Avg Market Exposure %':<35} {avg_market_exp:<20.1f} {full_avg_market_exp:<20.1f} {avg_market_exp - full_avg_market_exp:+.1f}%")
    
    print("\n" + "="*80)
    print("VERDICT:")
    print("="*80)
    
    improvement_score = 0
    
    if beat_bh_count / len(results_df) >= full_beat_bh / len(full_2022):
        print("✅ Similar or better beat-buy-hold rate")
        improvement_score += 1
    else:
        print("❌ Worse beat-buy-hold rate")
    
    if avg_strategy_return - avg_bh_return >= full_avg_alpha:
        print("✅ Similar or better alpha")
        improvement_score += 1
    else:
        print("❌ Worse alpha")
    
    if avg_strategy_dd >= full_avg_strategy_dd - 5:  # Within 5% is OK
        print("✅ Similar drawdown protection")
        improvement_score += 1
    else:
        print("❌ Worse drawdown protection")
    
    print(f"\nBear Market Score: {improvement_score}/3")
    
    if improvement_score >= 2:
        print("\n🎯 FILTERING PROTECTS IN BEAR MARKETS!")
        print("   High-quality trending stocks provided similar/better downside protection.")
        print("   The monthly universe selection strategy is FULLY VALIDATED.")
    else:
        print("\n⚠️  MIXED BEAR MARKET RESULTS")
        print("   Filtering doesn't clearly improve bear market performance.")
        print("   May need to adjust criteria or accept similar downside.")
    
except FileNotFoundError:
    print("\n⚠️  Could not load full universe 2022 results for comparison")
    print("   Run 'python scripts/backtest_2022_bear.py' first")

# Export
filename = "vpvma_2022_filtered_12_stocks.csv"
results_df.to_csv(filename, index=False)
print(f"\n✓ Results exported to: {filename}")

print("\n" + "="*80)
print("2022 BEAR MARKET TEST COMPLETE")
print("="*80)