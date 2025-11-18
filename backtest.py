"""
VPVMA Backtest with FastExit+SPY200 Protection
CORRECTED: Now uses Phase 3 validated sell logic with proper crossover detection

Run from project directory:
    python backtest_corrected.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from data.database import Database
from main import calculate_vpvma_indicator
from config import BUY_BANDWIDTH, SELL_BANDWIDTH
import warnings
warnings.filterwarnings('ignore')


class ProtectedPortfolio:
    """
    Full-universe VPVMA portfolio with FastExit+SPY200 protection
    
    Strategy:
    - Scan all 183 stocks daily for VPVMA signals
    - Rank buy signals by strength
    - Take top N strongest signals (max_positions limit)
    - Exit 2x faster when SPY < 200MA
    """
    
    def __init__(self, initial_capital=100000, max_positions=20, commission=1, slippage_bps=2):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.max_positions = max_positions
        self.commission = commission
        self.slippage_bps = slippage_bps
        
        self.positions = {}
        self.history = []
        self.trades = []
        
        # Protection state
        self.protection_active = False
        self.protection_days = 0
        self.total_days = 0
        
        # Tracking
        self.total_buy_signals = 0
        self.missed_signals = 0
        
        # Sell tracking
        self.fastexit_sells = 0
        self.normal_sells = 0
    
    def update_spy_regime(self, spy_data: pd.DataFrame, current_date: pd.Timestamp):
        """Update bear market regime using SPY 200MA"""
        spy_subset = spy_data[spy_data['timestamp'] <= current_date].tail(250)
        
        if len(spy_subset) < 200:
            self.protection_active = False
            return
        
        spy_subset = spy_subset.copy()
        spy_subset['ma_200'] = spy_subset['close'].rolling(window=200).mean()
        
        latest = spy_subset.iloc[-1]
        self.protection_active = latest['close'] < latest['ma_200']
        
        self.total_days += 1
        if self.protection_active:
            self.protection_days += 1
    
    def get_sell_bandwidth(self):
        """Get adaptive sell bandwidth based on regime"""
        if self.protection_active:
            return 0.04  # FastExit: 2x faster exits
        else:
            return SELL_BANDWIDTH  # Normal: 0.08
    
    def get_equity(self, current_prices):
        """Calculate total portfolio equity"""
        position_value = sum(
            pos['shares'] * current_prices.get(symbol, pos['entry_price'])
            for symbol, pos in self.positions.items()
        )
        return self.cash + position_value
    
    def execute_buy(self, symbol, price, date, strength):
        """Execute buy order"""
        if symbol in self.positions:
            return
        
        equity = self.get_equity({symbol: price})
        position_size = equity * 0.05  # 5% per position
        
        slippage = price * (self.slippage_bps / 10000)
        fill_price = price + slippage
        
        shares = int((position_size - self.commission) / fill_price)
        if shares <= 0:
            return
        
        cost = shares * fill_price + self.commission
        if cost > self.cash:
            return
        
        self.cash -= cost
        self.positions[symbol] = {
            'shares': shares,
            'entry_price': fill_price,
            'entry_date': date,
            'strength': strength
        }
        
        self.trades.append({
            'date': date,
            'symbol': symbol,
            'action': 'BUY',
            'shares': shares,
            'price': fill_price,
            'commission': self.commission,
            'protection_active': self.protection_active
        })
    
    def execute_sell(self, symbol, price, date, fast_exit=False):
        """Execute sell order"""
        if symbol not in self.positions:
            return
        
        pos = self.positions[symbol]
        slippage = price * (self.slippage_bps / 10000)
        fill_price = price - slippage
        
        proceeds = pos['shares'] * fill_price - self.commission
        self.cash += proceeds
        
        pnl = proceeds - (pos['shares'] * pos['entry_price'])
        hold_days = (date - pos['entry_date']).days
        
        self.trades.append({
            'date': date,
            'symbol': symbol,
            'action': 'SELL',
            'shares': pos['shares'],
            'price': fill_price,
            'commission': self.commission,
            'pnl': pnl,
            'hold_days': hold_days,
            'protection_active': self.protection_active,
            'fast_exit': fast_exit
        })
        
        if fast_exit:
            self.fastexit_sells += 1
        else:
            self.normal_sells += 1
        
        del self.positions[symbol]
    
    def record_snapshot(self, date, current_prices):
        """Record daily portfolio snapshot"""
        equity = self.get_equity(current_prices)
        
        self.history.append({
            'date': date,
            'equity': equity,
            'cash': self.cash,
            'num_positions': len(self.positions),
            'protection_active': self.protection_active
        })


def run_backtest(
    db: Database,
    symbols: list,
    start_date: str,
    end_date: str,
    initial_capital: int = 100000
):
    """
    Run full-universe VPVMA backtest with FastExit+SPY200 protection
    """
    
    print("=" * 80)
    print("VPVMA BACKTEST WITH FASTEXIT+SPY200 PROTECTION")
    print("=" * 80)
    print(f"Started: {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 80)
    print(f"Period: {start_date} to {end_date}")
    print(f"Capital: ${initial_capital:,}")
    print(f"Protection: ✅ ENABLED (exits 2x faster in bear markets)")
    print("=" * 80)
    
    portfolio = ProtectedPortfolio(initial_capital=initial_capital, max_positions=20)
    
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    
    print(f"📊 Universe: {len(symbols)} stocks")
    
    # Pre-calculate SPY regime for entire period
    print("🛡️ Pre-calculating SPY bear market regime...")
    spy_data = db.get_ohlcv_data('SPY', start_date=start - timedelta(days=365), end_date=end)
    print(f"   ✓ Loaded {len(spy_data)} days of SPY data")
    
    # Get all trading days from SPY
    trading_days = spy_data[
        (spy_data['timestamp'] >= start) & 
        (spy_data['timestamp'] <= end)
    ]['timestamp'].tolist()
    
    total_days = len(trading_days)
    print(f"Processing {total_days} trading days...")
    
    # Main backtest loop - DATE FIRST
    for day_idx, date in enumerate(trading_days):
        if day_idx % (total_days // 20) == 0:
            pct = int((day_idx / total_days) * 100)
            print(f"Progress: {pct}%", end=' ', flush=True)
        
        # Update protection regime
        portfolio.update_spy_regime(spy_data, date)
        
        current_prices = {}
        buy_signals_today = []
        
        # Scan full universe for signals
        for symbol in symbols:
            try:
                # Get data up to current date (no look-ahead bias)
                df = db.get_ohlcv_data(
                    symbol,
                    start_date=start - timedelta(days=365),
                    end_date=date
                )
                
                if len(df) < 50:
                    continue
                
                # Calculate VPVMA indicator
                result = calculate_vpvma_indicator(
                    high=df['high'].values,
                    low=df['low'].values,
                    close=df['close'].values,
                    open_price=df['open'].values,
                    volume=df['volume'].values
                )
                
                if len(result['vpvma']) == 0 or np.isnan(result['vpvma'][-1]):
                    continue
                
                current_price = df['close'].iloc[-1]
                current_prices[symbol] = current_price
                
                # Get signal values
                buy_signal = result['buy_signals'][-1]
                vpvma_val = result['vpvma'][-1]
                vpvmas_val = result['vpvmas'][-1]
                
                # Store buy signals for ranking
                if buy_signal:
                    buy_threshold = (1 + BUY_BANDWIDTH) * vpvmas_val
                    strength = (vpvma_val - buy_threshold) / buy_threshold if buy_threshold != 0 else 0
                    
                    buy_signals_today.append({
                        'symbol': symbol,
                        'price': current_price,
                        'strength': strength
                    })
                    portfolio.total_buy_signals += 1
                
                # Check sells for existing positions - CORRECTED PHASE 3 LOGIC
                if symbol in portfolio.positions:
                    # Get adaptive sell bandwidth based on regime
                    sell_bandwidth = portfolio.get_sell_bandwidth()
                    
                    # Calculate adaptive sell threshold
                    sell_threshold = (1 - sell_bandwidth * 2) * vpvmas_val
                    
                    # Check crossover condition (was above signal line previously)
                    if len(result['vpvma']) >= 2:
                        vpvma_prev = result['vpvma'][-2]
                        vpvmas_prev = result['vpvmas'][-2]
                        was_above = vpvma_prev >= vpvmas_prev
                    else:
                        was_above = False
                    
                    # PHASE 3 LOGIC: Sell if (was above) AND (now below adaptive threshold)
                    # This combines crossover detection with adaptive threshold
                    should_sell = was_above and (vpvma_val < sell_threshold)
                    
                    if should_sell:
                        portfolio.execute_sell(
                            symbol, 
                            current_price, 
                            date,
                            fast_exit=portfolio.protection_active
                        )
                
            except Exception as e:
                continue
        
        # Execute buys (take strongest signals first, up to max_positions)
        if buy_signals_today:
            buy_signals_today.sort(key=lambda x: x['strength'], reverse=True)
            
            available_slots = portfolio.max_positions - len(portfolio.positions)
            signals_to_execute = buy_signals_today[:available_slots]
            
            for signal in signals_to_execute:
                portfolio.execute_buy(
                    symbol=signal['symbol'],
                    price=signal['price'],
                    date=date,
                    strength=signal['strength']
                )
            
            portfolio.missed_signals += max(0, len(buy_signals_today) - available_slots)
        
        # Record daily snapshot
        portfolio.record_snapshot(date, current_prices)
    
    print("✓")
    
    # Calculate metrics
    df_history = pd.DataFrame(portfolio.history)
    df_trades = pd.DataFrame(portfolio.trades)
    
    total_return = (df_history['equity'].iloc[-1] / initial_capital - 1) * 100
    days_elapsed = (df_history['date'].iloc[-1] - df_history['date'].iloc[0]).days
    years = days_elapsed / 365.25
    cagr = ((df_history['equity'].iloc[-1] / initial_capital) ** (1/years) - 1) * 100
    
    # Calculate drawdown
    df_history['cummax'] = df_history['equity'].cummax()
    df_history['drawdown'] = (df_history['equity'] / df_history['cummax'] - 1) * 100
    max_dd = df_history['drawdown'].min()
    
    # Calculate returns
    df_history['returns'] = df_history['equity'].pct_change()
    annual_vol = df_history['returns'].std() * np.sqrt(252) * 100
    
    # Sharpe ratio
    mean_return = df_history['returns'].mean()
    std_return = df_history['returns'].std()
    sharpe = (mean_return / std_return * np.sqrt(252)) if std_return > 0 else 0
    
    # Sortino ratio
    downside_returns = df_history['returns'][df_history['returns'] < 0]
    downside_std = downside_returns.std()
    sortino = (mean_return / downside_std * np.sqrt(252)) if downside_std > 0 else 0
    
    # Omega ratio
    threshold = 0
    gains = df_history['returns'][df_history['returns'] > threshold].sum()
    losses = abs(df_history['returns'][df_history['returns'] < threshold].sum())
    omega = gains / losses if losses > 0 else 0
    
    # Calmar ratio
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0
    
    # Trade analysis
    sell_trades = df_trades[df_trades['action'] == 'SELL']
    winning_trades = sell_trades[sell_trades['pnl'] > 0]
    losing_trades = sell_trades[sell_trades['pnl'] <= 0]
    
    win_rate = len(winning_trades) / len(sell_trades) * 100 if len(sell_trades) > 0 else 0
    avg_win = winning_trades['pnl'].mean() if len(winning_trades) > 0 else 0
    avg_loss = losing_trades['pnl'].mean() if len(losing_trades) > 0 else 0
    avg_hold = sell_trades['hold_days'].mean() if 'hold_days' in sell_trades.columns else 0
    
    # Print results
    print("=" * 80)
    print("BACKTEST RESULTS")
    print("=" * 80)
    print("💰 RETURNS:")
    print(f"  Total Return: +{total_return:.2f}%")
    print(f"  CAGR: {cagr:.2f}%")
    print(f"  Final Equity: ${df_history['equity'].iloc[-1]:,.0f}")
    
    print("⚠️  RISK METRICS:")
    print(f"  Max Drawdown: {max_dd:.2f}%")
    print(f"  Sharpe Ratio: {sharpe:.2f}")
    print(f"  Sortino Ratio: {sortino:.2f}")
    print(f"  Omega Ratio: {omega:.2f}")
    print(f"  Calmar Ratio: {calmar:.2f}")
    print(f"  Annual Volatility: {annual_vol:.2f}%")
    
    print("💼 TRADING:")
    print(f"  Total Trades: {len(df_trades)}")
    print(f"  Win Rate: {win_rate:.1f}%")
    print(f"  Average Win: ${avg_win:.0f}")
    print(f"  Average Loss: ${avg_loss:.0f}")
    print(f"  Avg Hold: {avg_hold:.0f} days")
    print(f"  Unique Stocks: {df_trades['symbol'].nunique()}")
    
    print("🛡️ PROTECTION ACTIVATION:")
    print(f"  Total days: {portfolio.total_days}")
    print(f"  Protection ON: {portfolio.protection_days} ({portfolio.protection_days/portfolio.total_days*100:.1f}%)")
    print(f"  Normal regime: {portfolio.total_days - portfolio.protection_days} ({(portfolio.total_days-portfolio.protection_days)/portfolio.total_days*100:.1f}%)")
    print(f"  FastExit sells: {portfolio.fastexit_sells}")
    print(f"  Normal sells: {portfolio.normal_sells}")
    
    print("=" * 80)
    print("BACKTEST COMPLETE ✅")
    print("=" * 80)
    print(f"Finished: {datetime.now().strftime('%H:%M:%S')}")
    print("💡 EXPECTED (2024-2025 Holdout):")
    print("   Sharpe: ~1.13 (vs 0.98 baseline)")
    print("   CAGR: ~14.8% (vs 12.7% baseline)")
    print("   Protection: ~8-9% of days")
    print("=" * 80)
    
    return {
        'history': df_history,
        'trades': df_trades,
        'portfolio': portfolio,
        'metrics': {
            'total_return': total_return,
            'cagr': cagr,
            'sharpe': sharpe,
            'sortino': sortino,
            'max_dd': max_dd,
            'win_rate': win_rate
        }
    }


if __name__ == "__main__":
    db = Database(db_type='postgresql')
    
    # Load universe
    symbols_query = """
        SELECT DISTINCT symbol 
        FROM ohlcv_data 
        WHERE symbol != 'SPY'
        ORDER BY symbol
    """
    symbols_df = pd.read_sql(symbols_query, db.engine)
    symbols = symbols_df['symbol'].tolist()
    
    # Run backtest
    results = run_backtest(
        db=db,
        symbols=symbols,
        start_date='2005-01-01',
        end_date='2025-11-14',
        initial_capital=100000
    )