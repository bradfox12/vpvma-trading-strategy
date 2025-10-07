import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.database import Database
from main import calculate_vpvma_indicator
import pandas as pd
import numpy as np

print("="*70)
print("VPVMA BATCH BACKTEST - LONG ONLY (ALL SYMBOLS)")
print("="*70)

# Configuration
INITIAL_CAPITAL = 100000
COMMISSION_PER_TRADE = 1
SLIPPAGE_BPS = 2

db = Database(db_type='postgresql')
symbols = db.list_symbols()

print(f"\nTesting {len(symbols)} symbols: {', '.join(symbols)}")
print("="*70)

results = []

for symbol in symbols:
    print(f"\n[{symbols.index(symbol)+1}/{len(symbols)}] Testing {symbol}...", end=' ')
    
    try:
        # Get data and calculate VPVMA
        df = db.get_ohlcv_data(symbol)
        open_p, high, low, close, volume = db.get_ohlcv_arrays(symbol)
        
        result = calculate_vpvma_indicator(high, low, close, open_p, volume)
        
        df['vpvma'] = result['vpvma']
        df['vpvmas'] = result['vpvmas']
        df['signal'] = result['signals']
        df['buy_signal'] = result['buy_signals']
        df['sell_signal'] = result['sell_signals']
        
        df_valid = df[35:].copy().reset_index(drop=True)
        
        # Initialize backtest
        position = 0
        entry_price = 0
        trades = []
        equity_curve = [INITIAL_CAPITAL]
        cash = INITIAL_CAPITAL
        days_in_market = 0
        days_in_cash = 0
        
        # Run backtest
        for i in range(len(df_valid)):
            row = df_valid.iloc[i]
            
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
            # Buy & Hold
            bh_start = df_valid.iloc[0]['close']
            bh_end = df_valid.iloc[-1]['close']
            bh_return = ((bh_end - bh_start) / bh_start) * 100
            
            # Strategy metrics
            final_equity = equity_curve[-1]
            total_return = ((final_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL) * 100
            
            total_trades = len(trades_df)
            winning_trades = len(trades_df[trades_df['pnl'] > 0])
            win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0
            
            total_wins = trades_df[trades_df['pnl'] > 0]['pnl'].sum() if winning_trades > 0 else 0
            total_losses = abs(trades_df[trades_df['pnl'] < 0]['pnl'].sum()) if len(trades_df[trades_df['pnl'] < 0]) > 0 else 1
            profit_factor = total_wins / total_losses if total_losses > 0 else 0
            
            # Max drawdown
            equity_array = np.array(equity_curve)
            running_max = np.maximum.accumulate(equity_array)
            drawdown = (equity_array - running_max) / running_max * 100
            max_drawdown = drawdown.min()
            
            # Sharpe
            daily_returns = pd.Series(equity_curve).pct_change().dropna()
            sharpe = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252) if len(daily_returns) > 0 else 0
            
            # Market exposure
            market_exposure = (days_in_market / (days_in_market + days_in_cash)) * 100
            
            results.append({
                'Symbol': symbol,
                'Final_Equity': final_equity,
                'Strategy_Return_%': total_return,
                'BuyHold_Return_%': bh_return,
                'Alpha_%': total_return - bh_return,
                'Sharpe': sharpe,
                'Max_DD_%': max_drawdown,
                'Win_Rate_%': win_rate,
                'Profit_Factor': profit_factor,
                'Total_Trades': total_trades,
                'Market_Exp_%': market_exposure
            })
            
            print(f"✓ Return: {total_return:+.1f}% | B&H: {bh_return:+.1f}% | Sharpe: {sharpe:.2f}")
        else:
            print("✗ No trades")
            
    except Exception as e:
        print(f"✗ Error: {e}")

# Create results DataFrame
results_df = pd.DataFrame(results)

# Sort by Strategy Return
results_df = results_df.sort_values('Strategy_Return_%', ascending=False)

print("\n" + "="*70)
print("COMPREHENSIVE RESULTS TABLE")
print("="*70)

# Display formatted table
pd.set_option('display.max_columns', None)
pd.set_option('display.width', None)
pd.set_option('display.float_format', lambda x: f'{x:.2f}')

print("\n" + results_df.to_string(index=False))

# Summary statistics
print("\n" + "="*70)
print("SUMMARY STATISTICS")
print("="*70)

avg_return = results_df['Strategy_Return_%'].mean()
avg_sharpe = results_df['Sharpe'].mean()
avg_win_rate = results_df['Win_Rate_%'].mean()
profitable_count = len(results_df[results_df['Strategy_Return_%'] > 0])
beats_bh_count = len(results_df[results_df['Alpha_%'] > 0])

print(f"\nTotal Symbols Tested: {len(results_df)}")
print(f"Profitable: {profitable_count}/{len(results_df)} ({profitable_count/len(results_df)*100:.1f}%)")
print(f"Beat Buy & Hold: {beats_bh_count}/{len(results_df)} ({beats_bh_count/len(results_df)*100:.1f}%)")
print(f"\nAverage Strategy Return: {avg_return:.2f}%")
print(f"Average Sharpe Ratio: {avg_sharpe:.2f}")
print(f"Average Win Rate: {avg_win_rate:.1f}%")

# Best and worst performers
print("\n" + "="*70)
print("BEST & WORST PERFORMERS")
print("="*70)

print(f"\n🏆 BEST RETURN: {results_df.iloc[0]['Symbol']} (+{results_df.iloc[0]['Strategy_Return_%']:.1f}%)")
print(f"🏆 BEST SHARPE: {results_df.loc[results_df['Sharpe'].idxmax()]['Symbol']} ({results_df['Sharpe'].max():.2f})")
print(f"📉 WORST RETURN: {results_df.iloc[-1]['Symbol']} (+{results_df.iloc[-1]['Strategy_Return_%']:.1f}%)")

# Risk-adjusted ranking
results_df['Risk_Adj_Score'] = results_df['Strategy_Return_%'] * results_df['Sharpe']
results_df = results_df.sort_values('Risk_Adj_Score', ascending=False)

print("\n" + "="*70)
print("RISK-ADJUSTED RANKING (Return × Sharpe)")
print("="*70)

for idx, row in results_df.head(5).iterrows():
    print(f"{row['Symbol']:6} | Return: {row['Strategy_Return_%']:+7.1f}% | Sharpe: {row['Sharpe']:4.2f} | Score: {row['Risk_Adj_Score']:7.1f}")

# Export
filename = "vpvma_longonly_all_symbols_results.csv"
results_df.to_csv(filename, index=False)
print(f"\n✓ Full results exported to: {filename}")

print("\n" + "="*70)
print("BATCH BACKTEST COMPLETE")
print("="*70)