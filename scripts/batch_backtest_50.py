import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.database import Database
from main import calculate_vpvma_indicator
import pandas as pd
import numpy as np

print("="*70)
print("VPVMA COMPREHENSIVE TEST - 50 SYMBOLS")
print("="*70)

# Configuration
INITIAL_CAPITAL = 100000
COMMISSION_PER_TRADE = 1
SLIPPAGE_BPS = 2

db = Database(db_type='postgresql')
all_symbols = db.list_symbols()

print(f"\nTotal symbols in database: {len(all_symbols)}")
print(f"Testing all available symbols...")
print("="*70)

results = []
errors = []

for idx, symbol in enumerate(all_symbols, 1):
    print(f"\r[{idx}/{len(all_symbols)}] Testing {symbol:6}...", end='', flush=True)
    
    try:
        # Get data
        df = db.get_ohlcv_data(symbol)
        
        # Minimum data check
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
            
            # Calculate CAGR
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

print("\r" + " " * 70 + "\r", end='')  # Clear line

# Results DataFrame
results_df = pd.DataFrame(results)

if len(results_df) == 0:
    print("\n❌ No successful backtests!")
    exit(1)

results_df = results_df.sort_values('Return_%', ascending=False)

print("\n" + "="*70)
print(f"COMPREHENSIVE RESULTS - {len(results_df)} SYMBOLS")
print("="*70)

# Display summary stats first
print("\n📊 SUMMARY STATISTICS:")
print("="*70)

profitable_count = len(results_df[results_df['Return_%'] > 0])
beats_bh_count = len(results_df[results_df['Alpha_%'] > 0])
sharpe_gt_1_count = len(results_df[results_df['Sharpe'] > 1.0])

print(f"Total Symbols Tested: {len(results_df)}")
print(f"Profitable: {profitable_count}/{len(results_df)} ({profitable_count/len(results_df)*100:.1f}%)")
print(f"Beat Buy & Hold: {beats_bh_count}/{len(results_df)} ({beats_bh_count/len(results_df)*100:.1f}%)")
print(f"Sharpe > 1.0: {sharpe_gt_1_count}/{len(results_df)} ({sharpe_gt_1_count/len(results_df)*100:.1f}%)")

print(f"\nAverage Strategy Return: {results_df['Return_%'].mean():.2f}%")
print(f"Median Strategy Return: {results_df['Return_%'].median():.2f}%")
print(f"Average Sharpe Ratio: {results_df['Sharpe'].mean():.2f}")
print(f"Average Win Rate: {results_df['Win_Rate_%'].mean():.1f}%")
print(f"Average Market Exposure: {results_df['Market_Exp_%'].mean():.1f}%")

# Top performers
print("\n🏆 TOP 10 BY RETURN:")
print("="*70)
for idx, row in results_df.head(10).iterrows():
    print(f"{row['Symbol']:6} | Return: {row['Return_%']:+8.1f}% | Sharpe: {row['Sharpe']:4.2f} | Win Rate: {row['Win_Rate_%']:4.1f}%")

print("\n🏆 TOP 10 BY SHARPE:")
print("="*70)
top_sharpe = results_df.nlargest(10, 'Sharpe')
for idx, row in top_sharpe.iterrows():
    print(f"{row['Symbol']:6} | Sharpe: {row['Sharpe']:4.2f} | Return: {row['Return_%']:+8.1f}% | Max DD: {row['Max_DD_%']:+6.1f}%")

print("\n📉 BOTTOM 10:")
print("="*70)
for idx, row in results_df.tail(10).iterrows():
    print(f"{row['Symbol']:6} | Return: {row['Return_%']:+8.1f}% | Sharpe: {row['Sharpe']:4.2f} | Alpha: {row['Alpha_%']:+7.1f}%")

# Errors
if errors:
    print(f"\n⚠️  ERRORS ({len(errors)} symbols):")
    print("="*70)
    for symbol, error in errors[:10]:  # Show first 10
        print(f"{symbol:6}: {error}")
    if len(errors) > 10:
        print(f"... and {len(errors) - 10} more")

# Export
filename = "vpvma_50_symbols_comprehensive.csv"
results_df.to_csv(filename, index=False)
print(f"\n✓ Full results exported to: {filename}")

# Detailed table
print("\n" + "="*70)
print("FULL RESULTS TABLE (sorted by return):")
print("="*70)
pd.set_option('display.max_rows', None)
pd.set_option('display.float_format', lambda x: f'{x:.2f}')
print(results_df.to_string(index=False))

print("\n" + "="*70)
print("BATCH BACKTEST COMPLETE")
print("="*70)