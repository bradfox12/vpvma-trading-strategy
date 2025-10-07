import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.database import Database
from main import calculate_vpvma_indicator
import pandas as pd
import numpy as np

print("="*60)
print("VPVMA STRATEGY BACKTEST - LONG/SHORT")
print("="*60)

# Configuration
INITIAL_CAPITAL = 100000  # $100k starting capital
COMMISSION_PER_TRADE = 1  # $1 per trade (IB/Robinhood level)
SLIPPAGE_BPS = 2  # 2 basis points slippage per trade

db = Database(db_type='postgresql')
symbols = db.list_symbols()

print(f"\nAvailable symbols: {', '.join(symbols)}")
symbol = input(f"\nEnter symbol to backtest (default: SPY): ").upper() or 'SPY'

if symbol not in symbols:
    print(f"❌ Symbol not found!")
    exit(1)

print(f"\n{'='*60}")
print(f"BACKTESTING: {symbol} (LONG/SHORT)")
print(f"{'='*60}")
print(f"\nInitial Capital: ${INITIAL_CAPITAL:,.0f}")
print(f"Commission: ${COMMISSION_PER_TRADE} per trade")
print(f"Slippage: {SLIPPAGE_BPS} bps")
print(f"Strategy: Long on BUY signals, Short on SELL signals")

# Get data and calculate VPVMA
df = db.get_ohlcv_data(symbol)
open_p, high, low, close, volume = db.get_ohlcv_arrays(symbol)

result = calculate_vpvma_indicator(high, low, close, open_p, volume)

df['vpvma'] = result['vpvma']
df['vpvmas'] = result['vpvmas']
df['signal'] = result['signals']
df['buy_signal'] = result['buy_signals']
df['sell_signal'] = result['sell_signals']

# Filter warmup period
df_valid = df[35:].copy().reset_index(drop=True)

print(f"\nBacktest Period: {df_valid['timestamp'].min().date()} to {df_valid['timestamp'].max().date()}")
print(f"Total Days: {len(df_valid)}")

# Initialize backtest
position = 0  # positive = long shares, negative = short shares, 0 = no position
entry_price = 0
trades = []
equity_curve = [INITIAL_CAPITAL]
cash = INITIAL_CAPITAL
position_type = None  # 'LONG' or 'SHORT'

# Run backtest
for i in range(len(df_valid)):
    row = df_valid.iloc[i]
    
    # BUY SIGNAL - Go Long (or cover short and go long)
    if row['buy_signal']:
        # If currently short, close short position first
        if position < 0:
            # Close short (buy to cover)
            slippage_cost = row['close'] * (SLIPPAGE_BPS / 10000)
            exit_price = row['close'] + slippage_cost  # Buy at ask (higher)
            
            # P&L for short: profit when exit < entry
            pnl = (entry_price - exit_price) * abs(position)
            cash = INITIAL_CAPITAL + pnl - COMMISSION_PER_TRADE
            
            trades[-1]['exit_date'] = row['timestamp']
            trades[-1]['exit_price'] = exit_price
            trades[-1]['pnl'] = pnl
            trades[-1]['return_pct'] = ((entry_price - exit_price) / entry_price) * 100
            
            position = 0
        
        # Now go long
        if position == 0:
            slippage_cost = row['close'] * (SLIPPAGE_BPS / 10000)
            entry_price = row['close'] + slippage_cost
            shares = (cash - COMMISSION_PER_TRADE) / entry_price
            
            position = shares
            cash = 0
            position_type = 'LONG'
            
            trades.append({
                'entry_date': row['timestamp'],
                'entry_price': entry_price,
                'type': 'LONG',
                'shares': shares
            })
    
    # SELL SIGNAL - Go Short (or close long and go short)
    elif row['sell_signal']:
        # If currently long, close long position first
        if position > 0:
            # Close long (sell)
            slippage_cost = row['close'] * (SLIPPAGE_BPS / 10000)
            exit_price = row['close'] - slippage_cost  # Sell at bid (lower)
            
            # P&L for long: profit when exit > entry
            pnl = (exit_price - entry_price) * position
            cash = (exit_price * position) - COMMISSION_PER_TRADE
            
            trades[-1]['exit_date'] = row['timestamp']
            trades[-1]['exit_price'] = exit_price
            trades[-1]['pnl'] = pnl
            trades[-1]['return_pct'] = ((exit_price - entry_price) / entry_price) * 100
            
            position = 0
        
        # Now go short
        if position == 0:
            slippage_cost = row['close'] * (SLIPPAGE_BPS / 10000)
            entry_price = row['close'] - slippage_cost  # Sell at bid
            shares = (cash - COMMISSION_PER_TRADE) / entry_price
            
            position = -shares  # Negative = short
            cash = 0
            position_type = 'SHORT'
            
            trades.append({
                'entry_date': row['timestamp'],
                'entry_price': entry_price,
                'type': 'SHORT',
                'shares': shares
            })
    
    # Calculate current equity
    if position > 0:  # Long position
        current_equity = position * row['close']
    elif position < 0:  # Short position
        # Short P&L = entry_price - current_price
        unrealized_pnl = (entry_price - row['close']) * abs(position)
        current_equity = INITIAL_CAPITAL + unrealized_pnl
    else:  # No position
        current_equity = cash
    
    equity_curve.append(current_equity)

# Close any open position at end
if position != 0:
    final_price = df_valid.iloc[-1]['close']
    
    if position > 0:  # Close long
        pnl = (final_price - entry_price) * position
        cash = final_price * position
    else:  # Close short
        pnl = (entry_price - final_price) * abs(position)
        cash = INITIAL_CAPITAL + pnl
    
    trades[-1]['exit_date'] = df_valid.iloc[-1]['timestamp']
    trades[-1]['exit_price'] = final_price
    trades[-1]['pnl'] = pnl
    
    if position > 0:
        trades[-1]['return_pct'] = ((final_price - entry_price) / entry_price) * 100
    else:
        trades[-1]['return_pct'] = ((entry_price - final_price) / entry_price) * 100

# Calculate buy-and-hold benchmark
bh_start_price = df_valid.iloc[0]['close']
bh_end_price = df_valid.iloc[-1]['close']
bh_return = ((bh_end_price - bh_start_price) / bh_start_price) * 100
bh_final_value = INITIAL_CAPITAL * (1 + bh_return / 100)

# Calculate metrics
trades_df = pd.DataFrame([t for t in trades if 'exit_date' in t])

if len(trades_df) > 0:
    total_trades = len(trades_df)
    winning_trades = len(trades_df[trades_df['pnl'] > 0])
    losing_trades = len(trades_df[trades_df['pnl'] < 0])
    win_rate = (winning_trades / total_trades) * 100
    
    # Count long vs short trades
    long_trades = len(trades_df[trades_df['type'] == 'LONG'])
    short_trades = len(trades_df[trades_df['type'] == 'SHORT'])
    
    # Separate long/short performance
    long_pnl = trades_df[trades_df['type'] == 'LONG']['pnl'].sum() if long_trades > 0 else 0
    short_pnl = trades_df[trades_df['type'] == 'SHORT']['pnl'].sum() if short_trades > 0 else 0
    
    total_pnl = trades_df['pnl'].sum()
    avg_win = trades_df[trades_df['pnl'] > 0]['pnl'].mean() if winning_trades > 0 else 0
    avg_loss = trades_df[trades_df['pnl'] < 0]['pnl'].mean() if losing_trades > 0 else 0
    
    total_wins = trades_df[trades_df['pnl'] > 0]['pnl'].sum() if winning_trades > 0 else 0
    total_losses = abs(trades_df[trades_df['pnl'] < 0]['pnl'].sum()) if losing_trades > 0 else 1
    profit_factor = total_wins / total_losses if total_losses > 0 else 0
    
    final_equity = equity_curve[-1]
    total_return = ((final_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL) * 100
    
    # Calculate max drawdown
    equity_array = np.array(equity_curve)
    running_max = np.maximum.accumulate(equity_array)
    drawdown = (equity_array - running_max) / running_max * 100
    max_drawdown = drawdown.min()
    
    # Calculate Sharpe Ratio (assuming 252 trading days/year)
    daily_returns = pd.Series(equity_curve).pct_change().dropna()
    sharpe_ratio = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252) if len(daily_returns) > 0 else 0
    
    # Results
    print(f"\n{'='*60}")
    print("BACKTEST RESULTS")
    print(f"{'='*60}")
    
    print(f"\n💰 PERFORMANCE:")
    print(f"  Final Equity:        ${final_equity:,.2f}")
    print(f"  Total Return:        {total_return:+.2f}%")
    print(f"  Buy & Hold Return:   {bh_return:+.2f}%")
    print(f"  Alpha:               {total_return - bh_return:+.2f}%")
    
    print(f"\n📊 RISK METRICS:")
    print(f"  Max Drawdown:        {max_drawdown:.2f}%")
    print(f"  Sharpe Ratio:        {sharpe_ratio:.2f}")
    
    print(f"\n📈 TRADE STATISTICS:")
    print(f"  Total Trades:        {total_trades}")
    print(f"  Long Trades:         {long_trades} (P&L: ${long_pnl:,.2f})")
    print(f"  Short Trades:        {short_trades} (P&L: ${short_pnl:,.2f})")
    print(f"  Winning Trades:      {winning_trades}")
    print(f"  Losing Trades:       {losing_trades}")
    print(f"  Win Rate:            {win_rate:.1f}%")
    print(f"  Profit Factor:       {profit_factor:.2f}")
    
    print(f"\n💵 P&L BREAKDOWN:")
    print(f"  Total P&L:           ${total_pnl:,.2f}")
    print(f"  Avg Win:             ${avg_win:,.2f}")
    print(f"  Avg Loss:            ${avg_loss:,.2f}")
    print(f"  Total Commissions:   ${total_trades * COMMISSION_PER_TRADE * 2:,.0f}")
    
    print(f"\n{'='*60}")
    print("VERDICT:")
    print(f"{'='*60}")
    
    if total_return > bh_return and sharpe_ratio > 1.0:
        print("✅ STRATEGY BEATS BUY & HOLD")
        print(f"   Outperformance: {total_return - bh_return:+.2f}%")
        print(f"   Risk-adjusted: Sharpe {sharpe_ratio:.2f} (>1.0 is good)")
    elif total_return > bh_return:
        print("⚠️  BEATS BUY & HOLD BUT LOW SHARPE")
        print(f"   Outperformance: {total_return - bh_return:+.2f}%")
        print(f"   But Sharpe only {sharpe_ratio:.2f} (high risk)")
    else:
        print("❌ UNDERPERFORMS BUY & HOLD")
        print(f"   Underperformance: {total_return - bh_return:.2f}%")
        print(f"   Better to just hold {symbol}")
    
    # Export trades
    export = input(f"\nExport trade log to CSV? (y/n): ").lower()
    if export == 'y':
        filename = f"{symbol}_backtest_longshort_trades.csv"
        trades_df.to_csv(filename, index=False)
        print(f"✓ Exported to {filename}")

else:
    print("\n❌ No completed trades in backtest period")

print(f"\n{'='*60}")