import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.database import Database
from main import calculate_vpvma_indicator
import pandas as pd
import numpy as np

print("="*80)
print("HIGH-QUALITY FILTERED BACKTEST - VALIDATION TEST")
print("="*80)

# The 12 high-quality stocks identified by trend selector (as of Oct 6, 2025)
HIGH_QUALITY_SYMBOLS = [
    'INTC', 'LYFT', 'PLTR', 'SHOP', 'TSLA', 'UBER', 
    'NVDA', 'COIN', 'ORCL', 'AMD', 'AVGO', 'RBLX'
]

print(f"\nTesting Strategy: VPVMA Long-Only")
print(f"Universe: 12 High-Quality Trending Stocks")
print(f"Criteria: Score >75, Above MA200, ATR >2.5%")
print(f"Symbols: {', '.join(HIGH_QUALITY_SYMBOLS)}")
print("="*80)

# Configuration
INITIAL_CAPITAL = 100000
COMMISSION_PER_TRADE = 1
SLIPPAGE_BPS = 2

db = Database(db_type='postgresql')

results = []
errors = []

for idx, symbol in enumerate(HIGH_QUALITY_SYMBOLS, 1):
    print(f"\r[{idx}/{len(HIGH_QUALITY_SYMBOLS)}] Testing {symbol:6}...", end='', flush=True)
    
    try:
        df = db.get_ohlcv_data(symbol)
        
        if len(df) < 300:
            errors.append((symbol, f"Insufficient data ({len(df)} days)"))
            continue
        
        open_p, high, low, close, volume = db.get_ohlcv_arrays(symbol)
        result = calculate_vpvma_indicator(high, low, close, open_p, volume)
        
        df['vpvma'] = result['vpvma']
        df['vpvmas'] = result['vpvmas']
        df['signal'] = result['signals']
        df['buy_signal'] = result['buy_signals']
        df['sell_signal'] = result['sell_signals']
        
        df_valid = df[35:].copy().reset_index(drop=True)
        
        # Backtest
        position = 0
        entry_price = 0
        trades = []
        equity_curve = [INITIAL_CAPITAL]
        cash = INITIAL_CAPITAL
        days_in_market = 0
        days_in_cash = 0
        
        for i in range(len(df_valid)):
            row = df_valid.iloc[i]
            
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
        
        # Close final position
        if position > 0:
            final_price = df_valid.iloc[-1]['close']
            pnl = (final_price - entry_price) * position
            cash = final_price * position
            trades[-1]['exit_date'] = df_valid.iloc[-1]['timestamp']
            trades[-1]['exit_price'] = final_price
            trades[-1]['pnl'] = pnl
            trades[-1]['return_pct'] = ((final_price - entry_price) / entry_price) * 100
        
        # Calculate metrics
        trades_df = pd.DataFrame([t for t in trades if 'exit_date' in t])
        
        if len(trades_df) > 0:
            bh_start = df_valid.iloc[0]['close']
            bh_end = df_valid.iloc[-1]['close']
            bh_return = ((bh_end - bh_start) / bh_start) * 100
            
            final_equity = equity_curve[-1]
            total_return = ((final_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL) * 100
            
            total_trades = len(trades_df)
            winning_trades = len(trades_df[trades_df['pnl'] > 0])
            win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0
            
            total_wins = trades_df[trades_df['pnl'] > 0]['pnl'].sum() if winning_trades > 0 else 0
            total_losses = abs(trades_df[trades_df['pnl'] < 0]['pnl'].sum()) if len(trades_df[trades_df['pnl'] < 0]) > 0 else 1
            profit_factor = total_wins / total_losses if total_losses > 0 else 0
            
            equity_array = np.array(equity_curve)
            running_max = np.maximum.accumulate(equity_array)
            drawdown = (equity_array - running_max) / running_max * 100
            max_drawdown = drawdown.min()
            
            daily_returns = pd.Series(equity_curve).pct_change().dropna()
            sharpe = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252) if len(daily_returns) > 0 and daily_returns.std() > 0 else 0
            
            market_exposure = (days_in_market / (days_in_market + days_in_cash)) * 100
            
            years = len(df_valid) / 252
            cagr = (((final_equity / INITIAL_CAPITAL) ** (1 / years)) - 1) * 100 if years > 0 else 0
            
            results.append({
                'Symbol': symbol,
                'Final_Equity': final_equity,
                'Return_%': total_return,
                'BuyHold_Return_%': bh_return,
                'Alpha_%': total_return - bh_return,
                'CAGR_%': cagr,
                'Sharpe': sharpe,
                'Max_DD_%': max_drawdown,
                'Win_Rate_%': win_rate,
                'Profit_Factor': profit_factor,
                'Total_Trades': total_trades,
                'Market_Exp_%': market_exposure,
                'Days_Tested': len(df_valid)
            })
        else:
            errors.append((symbol, "No completed trades"))
            
    except Exception as e:
        errors.append((symbol, str(e)))

print("\r" + " " * 80 + "\r", end='')

# Results DataFrame
results_df = pd.DataFrame(results)

if len(results_df) == 0:
    print("\n❌ No successful backtests!")
    exit(1)

results_df = results_df.sort_values('Return_%', ascending=False)

print("\n" + "="*80)
print(f"HIGH-QUALITY FILTERED RESULTS ({len(results_df)} STOCKS)")
print("="*80)

# Summary stats
profitable_count = len(results_df[results_df['Return_%'] > 0])
beats_bh_count = len(results_df[results_df['Alpha_%'] > 0])
sharpe_gt_1_count = len(results_df[results_df['Sharpe'] > 1.0])

print(f"\n📊 FILTERED UNIVERSE PERFORMANCE:")
print(f"Total Stocks: {len(results_df)}")
print(f"Profitable: {profitable_count}/{len(results_df)} ({profitable_count/len(results_df)*100:.1f}%)")
print(f"Beat Buy & Hold: {beats_bh_count}/{len(results_df)} ({beats_bh_count/len(results_df)*100:.1f}%)")
print(f"Sharpe > 1.0: {sharpe_gt_1_count}/{len(results_df)} ({sharpe_gt_1_count/len(results_df)*100:.1f}%)")

avg_return = results_df['Return_%'].mean()
median_return = results_df['Return_%'].median()
avg_sharpe = results_df['Sharpe'].mean()
avg_win_rate = results_df['Win_Rate_%'].mean()
avg_market_exp = results_df['Market_Exp_%'].mean()

print(f"\nAverage Return: {avg_return:.2f}%")
print(f"Median Return: {median_return:.2f}%")
print(f"Average Sharpe: {avg_sharpe:.2f}")
print(f"Average Win Rate: {avg_win_rate:.1f}%")
print(f"Average Market Exposure: {avg_market_exp:.1f}%")

# Individual results
print("\n" + "="*80)
print("INDIVIDUAL STOCK RESULTS:")
print("="*80)

print("\n{:<8} {:>12} {:>10} {:>10} {:>8} {:>10}".format(
    "Symbol", "Return%", "B&H%", "Alpha%", "Sharpe", "Win Rate%"
))
print("-" * 80)

for idx, row in results_df.iterrows():
    print("{:<8} {:>12.1f} {:>10.1f} {:>10.1f} {:>8.2f} {:>10.1f}".format(
        row['Symbol'],
        row['Return_%'],
        row['BuyHold_Return_%'],
        row['Alpha_%'],
        row['Sharpe'],
        row['Win_Rate_%']
    ))

# Load full 54-stock results for comparison
print("\n" + "="*80)
print("COMPARISON: FILTERED vs FULL UNIVERSE")
print("="*80)

try:
    full_results = pd.read_csv('vpvma_50_symbols_comprehensive.csv')
    
    full_profitable = len(full_results[full_results['Return_%'] > 0])
    full_avg_return = full_results['Return_%'].mean()
    full_median_return = full_results['Return_%'].median()
    full_avg_sharpe = full_results['Sharpe'].mean()
    
    print(f"\n{'Metric':<30} {'Filtered (12)':<20} {'Full (54)':<20} {'Difference'}")
    print("-" * 80)
    print(f"{'Profitable %':<30} {profitable_count/len(results_df)*100:<20.1f} {full_profitable/len(full_results)*100:<20.1f} {(profitable_count/len(results_df) - full_profitable/len(full_results))*100:+.1f}%")
    print(f"{'Average Return %':<30} {avg_return:<20.1f} {full_avg_return:<20.1f} {avg_return - full_avg_return:+.1f}%")
    print(f"{'Median Return %':<30} {median_return:<20.1f} {full_median_return:<20.1f} {median_return - full_median_return:+.1f}%")
    print(f"{'Average Sharpe':<30} {avg_sharpe:<20.2f} {full_avg_sharpe:<20.2f} {avg_sharpe - full_avg_sharpe:+.2f}")
    
    print("\n" + "="*80)
    print("VERDICT:")
    print("="*80)
    
    improvement_score = 0
    
    if profitable_count / len(results_df) > full_profitable / len(full_results):
        print("✅ Higher profitable %")
        improvement_score += 1
    else:
        print("❌ Lower profitable %")
    
    if avg_return > full_avg_return:
        print("✅ Higher average return")
        improvement_score += 1
    else:
        print("❌ Lower average return")
    
    if median_return > full_median_return:
        print("✅ Higher median return")
        improvement_score += 1
    else:
        print("❌ Lower median return")
    
    if avg_sharpe > full_avg_sharpe:
        print("✅ Better risk-adjusted returns (Sharpe)")
        improvement_score += 1
    else:
        print("❌ Worse risk-adjusted returns")
    
    print(f"\nImprovement Score: {improvement_score}/4")
    
    if improvement_score >= 3:
        print("\n🎯 FILTERING WORKS! Pre-selecting trending stocks improves performance.")
        print("   The monthly universe selection strategy is VALIDATED.")
    elif improvement_score == 2:
        print("\n⚠️  MIXED RESULTS. Filtering shows some improvement but not decisive.")
        print("   Consider adjusting filtering criteria or testing longer period.")
    else:
        print("\n❌ FILTERING DOESN'T HELP. Pre-selection doesn't improve performance.")
        print("   May need to reconsider filtering approach or stick with full universe.")
    
except FileNotFoundError:
    print("\n⚠️  Could not load full universe results for comparison")
    print("   Run 'python scripts/batch_backtest.py' first to generate baseline")

# Export
filename = "vpvma_filtered_12_high_quality.csv"
results_df.to_csv(filename, index=False)
print(f"\n✓ Results exported to: {filename}")

print("\n" + "="*80)
print("VALIDATION TEST COMPLETE")
print("="*80)