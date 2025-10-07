"""
Portfolio Manager
Handles multiple positions, capital allocation, monthly rebalancing
"""

import pandas as pd
import numpy as np
from datetime import datetime

class PortfolioManager:
    """
    Manages portfolio with multiple positions and monthly rebalancing
    """
    
    def __init__(self, initial_capital=100000, commission=1, slippage_bps=2):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions = {}  # {symbol: {'shares': X, 'entry_price': Y, 'entry_date': Z}}
        self.commission = commission
        self.slippage_bps = slippage_bps
        
        self.current_universe = []
        self.history = []
        self.trades = []
        self.universe_changes = []
        
    def get_position_value(self, symbol, current_price):
        """Get current value of a position"""
        if symbol not in self.positions:
            return 0
        return self.positions[symbol]['shares'] * current_price
    
    def get_total_equity(self, current_prices):
        """Calculate total portfolio value"""
        positions_value = sum(
            self.get_position_value(symbol, current_prices.get(symbol, 0))
            for symbol in self.positions
        )
        return self.cash + positions_value
    
    def monthly_rebalance(self, new_universe, current_date, current_prices):
        """
        Compare current universe to new universe
        Exit positions in stocks that dropped out
        
        Args:
            new_universe: List of symbols in new universe
            current_date: Current date
            current_prices: Dict of {symbol: price}
        
        Returns:
            dropped: List of symbols that dropped out
            added: List of symbols that were added
        """
        old_universe = set(self.current_universe)
        new_universe_set = set(new_universe)
        
        dropped = old_universe - new_universe_set
        added = new_universe_set - old_universe
        
        # Exit all positions in dropped stocks
        for symbol in dropped:
            if symbol in self.positions:
                price = current_prices.get(symbol)
                if price:
                    self.exit_position(symbol, price, current_date, reason="Dropped from universe")
        
        # Update universe
        self.current_universe = new_universe
        
        # Log the change
        if dropped or added:
            self.universe_changes.append({
                'date': current_date,
                'dropped': list(dropped),
                'added': list(added),
                'universe_size': len(new_universe)
            })
            
            print(f"    Rebalance: Dropped {len(dropped)}, Added {len(added)}")
        
        return list(dropped), list(added)
    
    def enter_position(self, symbol, price, date):
        """
        Enter a new position
        Equal weight allocation across all universe stocks
        """
        if symbol in self.positions:
            return False  # Already in position
        
        if symbol not in self.current_universe:
            return False  # Not in current universe
        
        # Calculate position size (equal weight)
        total_equity = self.get_total_equity({symbol: price})
        target_allocation = total_equity / len(self.current_universe)
        
        # Account for slippage and commission
        slippage = price * (self.slippage_bps / 10000)
        entry_price = price + slippage
        
        shares = (target_allocation - self.commission) / entry_price
        
        if shares <= 0 or self.cash < (shares * entry_price + self.commission):
            return False  # Insufficient funds
        
        cost = shares * entry_price + self.commission
        self.cash -= cost
        
        self.positions[symbol] = {
            'shares': shares,
            'entry_price': entry_price,
            'entry_date': date
        }
        
        self.trades.append({
            'date': date,
            'symbol': symbol,
            'action': 'BUY',
            'shares': shares,
            'price': entry_price,
            'cost': cost,
            'reason': 'VPVMA buy signal'
        })
        
        return True
    
    def exit_position(self, symbol, price, date, reason="VPVMA sell signal"):
        """Exit a position"""
        if symbol not in self.positions:
            return False
        
        position = self.positions[symbol]
        shares = position['shares']
        
        # Account for slippage and commission
        slippage = price * (self.slippage_bps / 10000)
        exit_price = price - slippage
        
        proceeds = shares * exit_price - self.commission
        self.cash += proceeds
        
        pnl = proceeds - (position['entry_price'] * shares)
        pnl_pct = (exit_price - position['entry_price']) / position['entry_price'] * 100
        
        self.trades.append({
            'date': date,
            'symbol': symbol,
            'action': 'SELL',
            'shares': shares,
            'price': exit_price,
            'proceeds': proceeds,
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'reason': reason,
            'hold_days': (pd.to_datetime(date) - pd.to_datetime(position['entry_date'])).days
        })
        
        del self.positions[symbol]
        return True
    
    def process_vpvma_signal(self, symbol, signal_type, price, date):
        """
        Process a VPVMA buy or sell signal
        
        Args:
            symbol: Stock ticker
            signal_type: 'buy' or 'sell'
            price: Current price
            date: Signal date
        """
        if signal_type == 'buy':
            return self.enter_position(symbol, price, date)
        elif signal_type == 'sell':
            return self.exit_position(symbol, price, date)
        return False
    
    def record_daily_snapshot(self, date, current_prices):
        """Record portfolio state for equity curve"""
        equity = self.get_total_equity(current_prices)
        
        self.history.append({
            'date': date,
            'equity': equity,
            'cash': self.cash,
            'positions_value': equity - self.cash,
            'num_positions': len(self.positions),
            'positions': list(self.positions.keys())
        })
    
    def get_results_summary(self):
        """Get performance summary"""
        if len(self.history) == 0:
            return {}
        
        history_df = pd.DataFrame(self.history)
        trades_df = pd.DataFrame(self.trades)
        
        final_equity = history_df.iloc[-1]['equity']
        total_return = ((final_equity - self.initial_capital) / self.initial_capital) * 100
        
        # Drawdown analysis
        equity_curve = history_df['equity'].values
        running_max = np.maximum.accumulate(equity_curve)
        drawdown = (equity_curve - running_max) / running_max * 100
        max_drawdown = drawdown.min()
        
        # Trade statistics
        winning_trades = trades_df[trades_df['action'] == 'SELL'][trades_df['pnl'] > 0]
        losing_trades = trades_df[trades_df['action'] == 'SELL'][trades_df['pnl'] <= 0]
        
        return {
            'total_return_%': total_return,
            'final_equity': final_equity,
            'max_drawdown_%': max_drawdown,
            'num_trades': len(trades_df[trades_df['action'] == 'SELL']),
            'win_rate_%': (len(winning_trades) / len(trades_df[trades_df['action'] == 'SELL']) * 100) if len(trades_df) > 0 else 0,
            'avg_win': winning_trades['pnl'].mean() if len(winning_trades) > 0 else 0,
            'avg_loss': losing_trades['pnl'].mean() if len(losing_trades) > 0 else 0,
            'num_universe_changes': len(self.universe_changes),
            'history_df': history_df,
            'trades_df': trades_df
        }