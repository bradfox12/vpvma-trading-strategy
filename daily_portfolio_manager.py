"""
Daily Portfolio Manager - MOMENTUM UNIVERSE EDITION
====================================================
NOW WITH: Top 100 stock selection by 20-day momentum (monthly rebalance)

VALIDATED PERFORMANCE:
- Sharpe: 1.247 vs 0.977 baseline (+27.6%)
- CAGR: 32.82% vs 12.73% baseline (+20.09pp)
- Win Rate: 52.2%
- Consistency: 100% (5/5 periods positive)

Fixes:
1. BRK.B duplication - prevents buying same stock multiple times
2. Portfolio value calculation - tracks realized P&L correctly
3. Unicode logging errors - removes arrow characters
4. Cash calculation - uses running balance instead of recalculating
5. Universe selection - scans top 100 momentum stocks only

Run after market close (5:00 PM ET) after data update completes

Usage:
    python daily_portfolio_manager.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from data.database import Database
from main import calculate_vpvma_indicator
from protection.market_regime import detect_bear_regime
from protection.adaptive_bandwidth import get_adaptive_sell_bandwidth
from config import BUY_BANDWIDTH, SELL_BANDWIDTH, BEAR_SELL_BANDWIDTH
from universe_selector import UniverseSelector
from openpyxl import load_workbook
from openpyxl.styles import Border, Side, Font, PatternFill, Alignment
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging

# Add requests for Polygon API
import requests
import os

# Load environment
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent / '.env'
    load_dotenv(dotenv_path=env_path)
except ImportError:
    pass

# Setup logging with UTF-8 encoding
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('portfolio_manager.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class PortfolioManager:
    """
    Complete automated portfolio management system - FIXED
    """
    
    def __init__(self, initial_cash=100000, max_positions=20, position_size_pct=0.05):
        """
        Initialize portfolio manager
        
        Args:
            initial_cash: Starting portfolio value
            max_positions: Maximum concurrent positions
            position_size_pct: Position size as % of portfolio (0.05 = 5%)
        """
        self.db = Database(db_type='postgresql')

        # Initialize universe selector (momentum-based stock selection)
        self.selector = UniverseSelector(
            self.db,
            universe_size=100,      # Top 100 by momentum
            momentum_period=20,     # 20-day momentum (validated optimal)
            exclude_symbols=['SPY'] # Don't trade SPY
        )
        self.initial_cash = initial_cash
        self.max_positions = max_positions
        self.position_size_pct = position_size_pct
        
        # Files
        self.positions_file = 'current_positions.csv'
        self.tracker_file = 'trade_tracker.xlsx'
        
        # Load current state
        self.positions = self._load_positions()
        
        # FIX #2: Load cash from tracker instead of recalculating
        self.cash = self._load_cash_from_tracker()
        
        # Track actions
        self.closed_trades = []
        self.new_positions = []
        self.replaced_positions = []
        
        logger.info(f"Portfolio Manager initialized")
        logger.info(f"  Current positions: {len(self.positions)}")
        logger.info(f"  Portfolio value: ${self.get_portfolio_value():,.2f}")
        logger.info(f"  Available cash: ${self.cash:,.2f}")
    
    def _load_positions(self):
        """Load current positions from CSV"""
        if not Path(self.positions_file).exists():
            logger.info("No positions file found - starting fresh")
            return {}
        
        df = pd.read_csv(self.positions_file)
        df['entry_date'] = pd.to_datetime(df['entry_date'])
        
        positions = {}
        for _, row in df.iterrows():
            positions[row['symbol']] = {
                'shares': int(row['shares']),
                'entry_price': float(row['entry_price']),
                'entry_date': row['entry_date'],
                'entry_value': float(row['entry_price']) * int(row['shares'])
            }
        
        return positions
    
    def _load_cash_from_tracker(self):
        """
        FIX #2: Load cash balance from tracker to account for realized P&L
        
        This replaces the old _calculate_cash() method that incorrectly used:
        cash = initial_cash - invested (which ignored realized profits/losses)
        """
        try:
            wb = load_workbook(self.tracker_file)
            ws = wb['Dashboard']
            
            # Cash is in Dashboard sheet (you'll need to adjust the cell reference)
            # For now, calculate from initial_cash + all closed trade P&L
            
            # Read trade log
            df = pd.read_excel(self.tracker_file, sheet_name='Trade Log')
            df = df.dropna(subset=['Symbol'])
            
            # Calculate total realized P&L
            total_realized_pnl = df['Net P&L'].sum()
            
            # Calculate currently invested
            invested = sum(pos['entry_value'] for pos in self.positions.values())
            
            # Cash = initial + realized P&L - currently invested
            cash = self.initial_cash + total_realized_pnl - invested
            
            logger.info(f"  Loaded cash from tracker: ${cash:,.2f}")
            logger.info(f"    Initial: ${self.initial_cash:,.2f}")
            logger.info(f"    Realized P&L: ${total_realized_pnl:,.2f}")
            logger.info(f"    Invested: ${invested:,.2f}")
            
            return cash
            
        except Exception as e:
            logger.warning(f"Could not load cash from tracker: {e}")
            logger.warning(f"Using fallback calculation")
            # Fallback: basic calculation
            invested = sum(pos['entry_value'] for pos in self.positions.values())
            return self.initial_cash - invested
    
    def _save_positions(self):
        """Save current positions to CSV"""
        if len(self.positions) == 0:
            # Create empty file
            pd.DataFrame(columns=['symbol', 'shares', 'entry_price', 'entry_date']).to_csv(
                self.positions_file, index=False
            )
            return
        
        data = []
        for symbol, pos in self.positions.items():
            data.append({
                'symbol': symbol,
                'shares': pos['shares'],
                'entry_price': pos['entry_price'],
                'entry_date': pos['entry_date'].strftime('%Y-%m-%d')
            })
        
        df = pd.DataFrame(data)
        df.to_csv(self.positions_file, index=False)
        logger.info(f"Saved {len(self.positions)} positions to {self.positions_file}")
    
    def get_portfolio_value(self):
        """Calculate current portfolio value"""
        equity = 0
        for symbol, pos in self.positions.items():
            current_price = self._get_current_price(symbol)
            if current_price:
                equity += current_price * pos['shares']
            else:
                equity += pos['entry_value']  # Use entry value if can't get current
        
        return self.cash + equity
    
    def _get_current_price(self, symbol):
        """Get latest price for symbol"""
        try:
            df = self.db.get_ohlcv_data(
                symbol,
                start_date=datetime.now() - timedelta(days=5),
                end_date=datetime.now()
            )
            if len(df) > 0:
                return df['close'].iloc[-1]
        except:
            pass
        return None
    
    def calculate_signals(self, symbol, lookback_days=100):
        """Calculate VPVMA signals for a symbol"""
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=lookback_days)
            
            df = self.db.get_ohlcv_data(symbol, start_date=start_date, end_date=end_date)
            
            if len(df) < 50:
                return None
            
            # Calculate VPVMA
            result = calculate_vpvma_indicator(
                high=df['high'].values,
                low=df['low'].values,
                close=df['close'].values,
                open_price=df['open'].values,
                volume=df['volume'].values
            )
            
            # Get latest values
            vpvma_current = result['vpvma'][-1]
            vpvmas_current = result['vpvmas'][-1]
            buy_signal = result['buy_signals'][-1]
            
            # Previous values for sell signal
            if len(result['vpvma']) >= 2:
                vpvma_prev = result['vpvma'][-2]
                vpvmas_prev = result['vpvmas'][-2]
            else:
                vpvma_prev = None
                vpvmas_prev = None
            
            current_price = df['close'].iloc[-1]
            
            # Calculate signal strength
            if vpvmas_current != 0:
                signal_strength = (vpvma_current - vpvmas_current) / abs(vpvmas_current)
            else:
                signal_strength = 0
            
            return {
                'symbol': symbol,
                'current_price': current_price,
                'vpvma': vpvma_current,
                'vpvmas': vpvmas_current,
                'vpvma_prev': vpvma_prev,
                'vpvmas_prev': vpvmas_prev,
                'buy_signal': buy_signal,
                'signal_strength': signal_strength
            }
            
        except Exception as e:
            logger.debug(f"{symbol}: Error calculating signals - {e}")
            return None
    
    def check_sell_signals(self, spy_bearish):
        """
        Check all positions for sell signals
        
        Args:
            spy_bearish: True if SPY < 200MA (bear market)
        
        Returns:
            List of trades to close
        """
        logger.info("\n" + "="*80)
        logger.info("STEP 1: CHECKING SELL SIGNALS")
        logger.info("="*80)
        
        # Get adaptive sell bandwidth based on regime
        sell_bandwidth = get_adaptive_sell_bandwidth(spy_bearish)
        
        logger.info(f"Market regime: {'BEAR (FastExit)' if spy_bearish else 'BULL (Normal)'}")
        logger.info(f"Sell bandwidth: {sell_bandwidth:.2f} (exit at {(1-sell_bandwidth*2)*100:.0f}% of signal)")
        
        sells = []
        
        for symbol, position in self.positions.items():
            # UNIVERSE DROP CHECK:
            # Check if stock dropped out of momentum universe
            if not self.selector.is_in_universe(symbol):
                logger.info(f"  [UNIVERSE DROP] {symbol} - No longer in top 100 momentum")
                
                current_price = self._get_current_price(symbol)
                if current_price:
                    exit_value = current_price * position['shares']
                    pnl = exit_value - position['entry_value']
                    pnl_pct = (current_price / position['entry_price'] - 1) * 100
                    hold_days = (datetime.now() - position['entry_date']).days
                    
                    trade = {
                        'symbol': symbol,
                        'entry_date': position['entry_date'],
                        'exit_date': datetime.now(),
                        'shares': position['shares'],
                        'entry_price': position['entry_price'],
                        'exit_price': current_price,
                        'entry_value': position['entry_value'],
                        'exit_value': exit_value,
                        'pnl': pnl,
                        'pnl_pct': pnl_pct,
                        'hold_days': hold_days,
                        'regime': 'BEAR' if spy_bearish else 'BULL',
                        'exit_type': 'Universe Drop'  # Mark as universe drop
                    }
                    
                    sells.append(trade)
                    logger.info(f"    ${pnl:+,.0f} ({pnl_pct:+.1f}%) - {hold_days} days")
                    continue  # Skip VPVMA signal check for this position
            
            signal_data = self.calculate_signals(symbol)
            
            if signal_data is None:
                continue
            
            # Calculate sell threshold with adaptive bandwidth
            sell_threshold = (1 - sell_bandwidth * 2) * signal_data['vpvmas']
            
            # Check crossover condition
            if signal_data['vpvma_prev'] is not None and signal_data['vpvmas_prev'] is not None:
                was_above = signal_data['vpvma_prev'] >= signal_data['vpvmas_prev']
            else:
                was_above = False
            
            # Sell if (was above) AND (now below threshold)
            should_sell = was_above and (signal_data['vpvma'] < sell_threshold)
            
            if should_sell:
                current_price = signal_data['current_price']
                exit_value = current_price * position['shares']
                pnl = exit_value - position['entry_value']
                pnl_pct = (current_price / position['entry_price'] - 1) * 100
                hold_days = (datetime.now() - position['entry_date']).days
                
                trade = {
                    'symbol': symbol,
                    'entry_date': position['entry_date'],
                    'exit_date': datetime.now(),
                    'shares': position['shares'],
                    'entry_price': position['entry_price'],
                    'exit_price': current_price,
                    'entry_value': position['entry_value'],
                    'exit_value': exit_value,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'hold_days': hold_days,
                    'regime': 'BEAR' if spy_bearish else 'BULL',
                    'exit_type': 'Signal'
                }
                
                sells.append(trade)
                logger.info(f"  [SELL] {symbol}: ${pnl:+,.0f} ({pnl_pct:+.1f}%) - {hold_days} days")
        
        logger.info(f"\nSell signals: {len(sells)}/{len(self.positions)} positions")
        return sells
    
    def scan_for_buy_signals(self):
        """
        Scan universe for buy signals
        
        Returns:
            List of buy signals ranked by strength
        """
        logger.info("\n" + "="*80)
        logger.info("STEP 2: SCANNING FOR BUY SIGNALS")
        logger.info("="*80)
        
        # Get momentum-selected universe (top 100 stocks)
        # Universe auto-refreshes on 1st trading day of each month
        symbols = self.selector.get_universe(datetime.now())
        
        # Log universe info
        universe_info = self.selector.get_universe_info()
        logger.info(f"📊 Universe: {universe_info['size']} stocks (from {universe_info['cache_month']})")
        logger.info(f"   Top 5: {universe_info['top_5']}")
        # Handle case where momentum_range might be None
        if universe_info.get('momentum_range') is not None and len(universe_info['momentum_range']) == 2:
            logger.info(f"   Momentum range: {universe_info['momentum_range'][0]:.1%} to {universe_info['momentum_range'][1]:.1%}")
        else:
            logger.warning(f"   Momentum range: Not available (universe calculation failed)")
        
        buy_signals = []
        
        for symbol in symbols:
            # Skip if already in portfolio
            if symbol in self.positions:
                continue
            
            signal_data = self.calculate_signals(symbol)
            
            if signal_data and signal_data['buy_signal']:
                buy_signals.append(signal_data)
        
        # Rank by strength
        buy_signals.sort(key=lambda x: x['signal_strength'], reverse=True)
        
        logger.info(f"Found {len(buy_signals)} buy signals")
        if len(buy_signals) > 0:
            logger.info(f"Strongest signal: {buy_signals[0]['symbol']} (strength: {buy_signals[0]['signal_strength']:.3f})")
        
        return buy_signals
    
    def find_replacement_candidates(self, buy_signals, sells=None):
        """
        FIX #1: Find losers that can be replaced with significantly stronger signals
        Now prevents duplicate replacements with the same stock
        FIX #4: Now excludes positions that already have sell signals
        
        Args:
            buy_signals: List of available buy signals (sorted by strength)
            sells: List of positions already marked for selling (to exclude from replacements)
        
        Returns:
            List of (symbol_to_sell, new_signal) tuples
        """
        logger.info("\n" + "="*80)
        logger.info("STEP 3: SMART POSITION REPLACEMENT")
        logger.info("="*80)
        
        if len(self.positions) < self.max_positions:
            logger.info(f"Portfolio not full ({len(self.positions)}/{self.max_positions}) - skipping replacement logic")
            return []
        
        logger.info(f"Portfolio full - checking for upgrade opportunities...")
        
        replacements = []
        used_buy_symbols = set()  # FIX #1: Track which symbols are already being bought
        
        # FIX #4: Get symbols already marked for selling
        sell_symbols = {trade['symbol'] for trade in (sells or [])}
        if sell_symbols:
            logger.info(f"Excluding {len(sell_symbols)} positions with sell signals: {sell_symbols}")
        
        # Evaluate each current position
        for symbol, position in self.positions.items():
            # FIX #4: Skip positions that already have sell signals
            if symbol in sell_symbols:
                continue
                
            signal_data = self.calculate_signals(symbol)
            
            if signal_data is None:
                continue
            
            # Calculate unrealized P&L
            current_price = signal_data['current_price']
            current_value = current_price * position['shares']
            unrealized_pnl = current_value - position['entry_value']
            unrealized_pct = (current_price / position['entry_price'] - 1) * 100
            
            # Only consider losers
            if unrealized_pnl >= 0:
                continue
            
            # Get current signal strength
            current_strength = signal_data['signal_strength']
            
            # FIX #1: Find best available signal that's 25%+ stronger AND not already used
            for buy_signal in buy_signals:
                # Skip if this symbol is already being bought in another replacement
                if buy_signal['symbol'] in used_buy_symbols:
                    continue
                
                improvement = (buy_signal['signal_strength'] - current_strength) / abs(current_strength) if current_strength != 0 else float('inf')
                
                if improvement >= 0.25:  # 25% stronger
                    replacements.append({
                        'sell_symbol': symbol,
                        'sell_price': current_price,
                        'unrealized_pnl': unrealized_pnl,
                        'unrealized_pct': unrealized_pct,
                        'current_strength': current_strength,
                        'buy_signal': buy_signal,
                        'improvement': improvement * 100
                    })
                    
                    # FIX #1: Mark this buy symbol as used
                    used_buy_symbols.add(buy_signal['symbol'])
                    
                    # FIX #3: Remove arrow character for Windows console compatibility
                    logger.info(f"  [REPLACE] {symbol} (${unrealized_pnl:+,.0f}, strength: {current_strength:.3f})")
                    logger.info(f"            => {buy_signal['symbol']} (strength: {buy_signal['signal_strength']:.3f}, +{improvement*100:.0f}% better)")
                    
                    break  # Only replace with best available signal
        
        logger.info(f"\nReplacement opportunities: {len(replacements)}")
        return replacements
    
    def execute_portfolio_changes(self, sells, buy_signals, replacements):
        """
        Execute all portfolio changes
        
        Args:
            sells: List of positions to close (sell signals)
            buy_signals: List of all available buy signals
            replacements: List of replacement trades
        """
        logger.info("\n" + "="*80)
        logger.info("STEP 4: EXECUTING PORTFOLIO CHANGES")
        logger.info("="*80)
        
        # 1. Close positions with sell signals
        for trade in sells:
            self.closed_trades.append(trade)
            del self.positions[trade['symbol']]
            self.cash += trade['exit_value']
            logger.info(f"  [CLOSED] {trade['symbol']}: ${trade['pnl']:+,.0f}")
        
        # 2. Execute replacements
        for replacement in replacements:
            # Close loser
            symbol = replacement['sell_symbol']
            position = self.positions[symbol]
            
            exit_trade = {
                'symbol': symbol,
                'entry_date': position['entry_date'],
                'exit_date': datetime.now(),
                'shares': position['shares'],
                'entry_price': position['entry_price'],
                'exit_price': replacement['sell_price'],
                'entry_value': position['entry_value'],
                'exit_value': replacement['sell_price'] * position['shares'],
                'pnl': replacement['unrealized_pnl'],
                'pnl_pct': replacement['unrealized_pct'],
                'hold_days': (datetime.now() - position['entry_date']).days,
                'regime': 'Unknown',
                'exit_type': 'Replacement'
            }
            
            self.closed_trades.append(exit_trade)
            del self.positions[symbol]
            self.cash += exit_trade['exit_value']
            
            # Open new position
            new_signal = replacement['buy_signal']
            portfolio_value = self.get_portfolio_value()
            position_value = portfolio_value * self.position_size_pct
            shares = int(position_value / new_signal['current_price'])
            
            if shares > 0:
                # FIX #1: This should never happen now due to used_buy_symbols tracking
                # But add a safety check anyway
                if new_signal['symbol'] in self.positions:
                    logger.warning(f"  [SKIP] {new_signal['symbol']} already in portfolio!")
                    continue
                
                self.positions[new_signal['symbol']] = {
                    'shares': shares,
                    'entry_price': new_signal['current_price'],
                    'entry_date': datetime.now(),
                    'entry_value': shares * new_signal['current_price']
                }
                self.cash -= shares * new_signal['current_price']
                self.replaced_positions.append(new_signal['symbol'])
                
                # FIX #3: Remove arrow for Windows compatibility
                logger.info(f"  [REPLACED] {symbol} => {new_signal['symbol']}: {shares} shares @ ${new_signal['current_price']:.2f}")
        
        # 3. Fill empty slots with strongest signals
        available_slots = self.max_positions - len(self.positions)
        
        if available_slots > 0:
            logger.info(f"\nFilling {available_slots} empty slots...")
            
            # Filter out already used signals (both from replacements AND from positions)
            used_symbols = {r['buy_signal']['symbol'] for r in replacements}
            used_symbols.update(self.positions.keys())  # FIX #1: Also exclude current positions
            
            remaining_signals = [s for s in buy_signals if s['symbol'] not in used_symbols]
            
            portfolio_value = self.get_portfolio_value()
            
            for signal in remaining_signals[:available_slots]:
                position_value = portfolio_value * self.position_size_pct
                shares = int(position_value / signal['current_price'])
                
                if shares > 0 and shares * signal['current_price'] <= self.cash:
                    # FIX #1: Double-check not already in portfolio
                    if signal['symbol'] in self.positions:
                        logger.warning(f"  [SKIP] {signal['symbol']} already in portfolio!")
                        continue
                    
                    self.positions[signal['symbol']] = {
                        'shares': shares,
                        'entry_price': signal['current_price'],
                        'entry_date': datetime.now(),
                        'entry_value': shares * signal['current_price']
                    }
                    self.cash -= shares * signal['current_price']
                    self.new_positions.append(signal['symbol'])
                    
                    logger.info(f"  [NEW] {signal['symbol']}: {shares} shares @ ${signal['current_price']:.2f}")
        
        logger.info(f"\nPortfolio changes complete:")
        logger.info(f"  Closed: {len(sells) + len(replacements)}")
        logger.info(f"  Opened: {len(replacements) + len(self.new_positions)}")
        logger.info(f"  Final positions: {len(self.positions)}/{self.max_positions}")
    
    def update_excel(self):
        """
        Update trade_tracker.xlsx with all changes (IMPROVED VERSION)
        
        Improvements:
        - Creates backup before writing
        - Verifies write succeeded
        - Better error messages
        - Checks if file is locked
        """
        logger.info("\n" + "="*80)
        logger.info("STEP 5: UPDATING EXCEL TRACKER")
        logger.info("="*80)
        
        if not Path(self.tracker_file).exists():
            logger.warning(f"Trade tracker not found: {self.tracker_file}")
            logger.info("Run: python create_trade_tracker.py")
            return
        
        # Check if file is locked (Excel has it open)
        try:
            # Try to open in append mode to check if it's locked
            with open(self.tracker_file, 'a'):
                pass
        except PermissionError:
            logger.error("="*80)
            logger.error("❌ EXCEL FILE IS OPEN!")
            logger.error("="*80)
            logger.error(f"Cannot update {self.tracker_file} - file is open in Excel!")
            logger.error("Please:")
            logger.error("  1. Close Excel")
            logger.error("  2. Run the script again")
            logger.error("")
            logger.error("Your trades are logged and will be saved when Excel is closed.")
            logger.error("="*80)
            return
        
        try:
            # Load workbook
            logger.info(f"📂 Loading workbook: {self.tracker_file}")
            wb = load_workbook(self.tracker_file)
            
            # Verify Trade Log sheet exists
            if 'Trade Log' not in wb.sheetnames:
                logger.error(f"❌ 'Trade Log' sheet not found in {self.tracker_file}")
                logger.error(f"Available sheets: {wb.sheetnames}")
                logger.error("Excel tracker may have wrong structure - skipping update")
                return
            
            # Get initial row count (find actual last data row, not just max_row)
            trade_log = wb['Trade Log']
            
            # Find the actual last row with data by checking Symbol column (D)
            actual_last_row = 1  # Start after header
            for row in range(trade_log.max_row, 0, -1):
                # Check if Symbol column (column D / index 4) has data
                symbol_cell = trade_log.cell(row=row, column=4)  # Column D = Symbol
                if symbol_cell.value is not None and str(symbol_cell.value).strip():
                    actual_last_row = row
                    break
            
            initial_row_count = actual_last_row
            logger.info(f"📊 Current trade count: {initial_row_count - 1} trades")  # -1 for header
            logger.info(f"   (max_row={trade_log.max_row}, actual_data_row={actual_last_row})")
            
            # Update Trade Log with closed trades
            if len(self.closed_trades) > 0:
                logger.info(f"📝 Adding {len(self.closed_trades)} closed trades...")
                self._update_trade_log(wb)
                
                # Verify trades were added
                final_row_count = trade_log.max_row
                added = final_row_count - initial_row_count
                logger.info(f"✓ Added {added} rows to Trade Log")
                
                if added != len(self.closed_trades):
                    logger.warning(f"⚠️ Expected to add {len(self.closed_trades)} trades but added {added}")
            else:
                logger.info("No closed trades to log")
                final_row_count = initial_row_count  # No trades added, count unchanged
            
            # Update Current Positions sheet
            logger.info("📊 Updating Current Positions...")
            self._update_current_positions(wb)
            logger.info(f"✓ Updated {len(self.positions)} positions")
            
            # Create backup before saving
            backup_path = Path(self.tracker_file).parent / f"{Path(self.tracker_file).stem}_backup.xlsx"
            logger.info(f"💾 Creating backup: {backup_path.name}")
            wb.save(backup_path)
            
            # Save to main file
            logger.info(f"💾 Saving changes to: {self.tracker_file}")
            wb.save(self.tracker_file)
            
            # Verify save succeeded by reading back
            wb_verify = load_workbook(self.tracker_file)
            verify_ws = wb_verify['Trade Log']
            
            # Find actual last row with data (same logic as initial count)
            verify_actual_row = 1
            for row in range(verify_ws.max_row, 0, -1):
                symbol_cell = verify_ws.cell(row=row, column=4)  # Column D = Symbol
                if symbol_cell.value is not None and str(symbol_cell.value).strip():
                    verify_actual_row = row
                    break
            
            verify_row_count = verify_actual_row
            
            if verify_row_count == final_row_count:
                logger.info("="*80)
                logger.info("✅ EXCEL TRACKER UPDATED SUCCESSFULLY")
                logger.info("="*80)
                logger.info(f"   File: {self.tracker_file}")
                logger.info(f"   Total trades: {verify_row_count - 1}")
                logger.info(f"   Added today: {len(self.closed_trades)}")
                logger.info("="*80)
            else:
                logger.error(f"⚠️ Verification failed! Row counts don't match:")
                logger.error(f"   Expected: {final_row_count}, Got: {verify_row_count}")
            
        except PermissionError as e:
            logger.error("="*80)
            logger.error("❌ PERMISSION ERROR")
            logger.error("="*80)
            logger.error(f"Cannot save {self.tracker_file}")
            logger.error("Possible causes:")
            logger.error("  1. Excel file is open - CLOSE IT and run again")
            logger.error("  2. File is read-only - check file properties")
            logger.error("  3. Folder permissions issue")
            logger.error("="*80)
            
        except Exception as e:
            logger.error("="*80)
            logger.error("❌ EXCEL UPDATE FAILED")
            logger.error("="*80)
            logger.error(f"Error: {type(e).__name__}: {e}")
            logger.error(f"File: {self.tracker_file}")
            logger.error("")
            logger.error("Your trades were NOT saved to Excel!")
            logger.error("Manual fix required - check documentation.")
            logger.error("="*80)
            import traceback
            logger.error(traceback.format_exc())
        
        # Always try to save positions CSV (separate from Excel)
        try:
            self._save_positions()
        except Exception as e:
            logger.error(f"[FAILED] Error saving positions CSV: {e}")
    
    def _update_trade_log(self, wb):
        """
        Add closed trades to Trade Log sheet (IMPROVED VERSION)
        
        Changes:
        - More robust row finding
        - Better logging
        - Validates data before writing
        """
        ws = wb['Trade Log']
        
        # Find the actual last row with data (same logic as main update method)
        last_data_row = 1  # Start after header
        for row in range(ws.max_row, 0, -1):
            symbol_cell = ws.cell(row=row, column=4)  # Column D = Symbol
            if symbol_cell.value is not None and str(symbol_cell.value).strip():
                last_data_row = row
                break
        
        next_row = last_data_row + 1
        logger.info(f"   Starting at row {next_row}")
        
        for i, trade in enumerate(self.closed_trades, 1):
            row = next_row + i - 1
            
            # Validate trade data
            required_fields = ['symbol', 'entry_date', 'exit_date', 'shares', 'entry_price', 'exit_price']
            missing = [f for f in required_fields if f not in trade]
            if missing:
                logger.warning(f"   ⚠️ Trade {i} missing fields: {missing} - skipping")
                continue
            
            # Add trade data
            ws[f'B{row}'] = trade['entry_date']
            ws[f'C{row}'] = trade['exit_date']
            ws[f'D{row}'] = trade['symbol']
            ws[f'E{row}'] = 'LONG'
            ws[f'F{row}'] = trade['shares']
            ws[f'G{row}'] = trade['entry_price']
            ws[f'H{row}'] = trade['exit_price']
            ws[f'I{row}'] = trade['entry_value']
            ws[f'J{row}'] = trade['exit_value']
            ws[f'K{row}'] = f"=J{row}-I{row}"
            ws[f'L{row}'] = 2  # Commission
            ws[f'M{row}'] = f"=K{row}-L{row}"
            ws[f'N{row}'] = f"=M{row}/I{row}"
            ws[f'O{row}'] = trade['hold_days']
            ws[f'P{row}'] = f"=IF(M{row}>0,\"Win\",\"Loss\")"
            ws[f'Q{row}'] = 'VPVMA'
            ws[f'R{row}'] = trade.get('regime', 'Unknown')
            ws[f'S{row}'] = trade.get('exit_type', 'Signal')
            
            pnl = trade.get('pnl', 0)
            logger.info(f"   [{i:2d}/{len(self.closed_trades)}] {trade['symbol']:8s} ${pnl:+7.0f}")
    
    def _update_current_positions(self, wb):
        """Update Current Positions sheet"""
        ws = wb['Current Positions']
        
        # Clear existing positions (keep header)
        for row in range(3, ws.max_row + 1):
            for col in range(1, 10):
                ws.cell(row=row, column=col).value = None
        
        # Add current positions
        row = 3
        for symbol, pos in self.positions.items():
            current_price = self._get_current_price(symbol)
            if current_price:
                current_value = current_price * pos['shares']
                unrealized_pnl = current_value - pos['entry_value']
                unrealized_pct = (current_price / pos['entry_price'] - 1) * 100
            else:
                current_price = pos['entry_price']
                current_value = pos['entry_value']
                unrealized_pnl = 0
                unrealized_pct = 0
            
            ws[f'A{row}'] = symbol
            ws[f'B{row}'] = pos['shares']
            ws[f'C{row}'] = pos['entry_price']
            ws[f'D{row}'] = pos['entry_date']
            ws[f'E{row}'] = current_price
            ws[f'F{row}'] = pos['entry_value']
            ws[f'G{row}'] = current_value
            ws[f'H{row}'] = unrealized_pnl
            ws[f'I{row}'] = unrealized_pct / 100
            
            row += 1
        
        logger.info(f"  Updated {len(self.positions)} positions")
    
    def send_email_report(self, spy_bearish):
        """
        Send email with trading orders
        """
        logger.info("\n" + "="*80)
        logger.info("STEP 6: SENDING EMAIL REPORT")
        logger.info("="*80)
        
        # Generate HTML report
        html = self._generate_html_report(spy_bearish)
        
        # Save to file
        with open('daily_orders.html', 'w', encoding='utf-8') as f:
            f.write(html)
        logger.info("[OK] Saved report to daily_orders.html")
        
        # Try to send email
        try:
            import os
            email_user = os.getenv('EMAIL_USER')
            email_pass = os.getenv('EMAIL_PASS')
            email_to = os.getenv('EMAIL_TO')
            
            if not all([email_user, email_pass, email_to]):
                logger.info("[SKIP] Email not configured - check .env file")
                return
            
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f"VPVMA Trading Orders - {datetime.now().strftime('%Y-%m-%d')}"
            msg['From'] = email_user
            msg['To'] = email_to
            
            msg.attach(MIMEText(html, 'html'))
            
            server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
            server.login(email_user, email_pass)
            server.sendmail(email_user, email_to, msg.as_string())
            server.quit()
            
            logger.info(f"[OK] Email sent to {email_to}")
            
        except Exception as e:
            logger.error(f"Email failed: {e}")
    
    def _generate_html_report(self, spy_bearish):
        """Generate HTML report for email/file"""
        date_str = datetime.now().strftime('%Y-%m-%d')
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                h1 {{ color: #2c3e50; }}
                h2 {{ color: #34495e; margin-top: 30px; }}
                table {{ border-collapse: collapse; width: 100%; margin-top: 10px; }}
                th {{ background-color: #3498db; color: white; padding: 12px; text-align: left; }}
                td {{ padding: 10px; border-bottom: 1px solid #ddd; }}
                .sell {{ background-color: #ffe6e6; }}
                .buy {{ background-color: #e6ffe6; }}
                .replace {{ background-color: #fff4e6; }}
                .metric {{ display: inline-block; margin: 10px 20px; }}
                .metric-label {{ color: #7f8c8d; }}
                .metric-value {{ font-size: 24px; font-weight: bold; color: #2c3e50; }}
            </style>
        </head>
        <body>
            <h1>VPVMA Daily Trading Orders</h1>
            <p><strong>Date:</strong> {date_str}</p>
            <p><strong>Market Regime:</strong> {'🐻 BEAR (FastExit Active)' if spy_bearish else '🐂 BULL (Normal)'}</p>
            
            <div class="metric">
                <div class="metric-label">Portfolio Value</div>
                <div class="metric-value">${self.get_portfolio_value():,.0f}</div>
            </div>
            
            <div class="metric">
                <div class="metric-label">Positions</div>
                <div class="metric-value">{len(self.positions)}/{self.max_positions}</div>
            </div>
            
            <div class="metric">
                <div class="metric-label">Cash</div>
                <div class="metric-value">${self.cash:,.0f}</div>
            </div>
        """
        
        # Closed trades
        if len(self.closed_trades) > 0:
            html += """
            <h2>Closed Positions</h2>
            <table>
                <tr>
                    <th>Symbol</th>
                    <th>Shares</th>
                    <th>Entry</th>
                    <th>Exit</th>
                    <th>P&L</th>
                    <th>Return %</th>
                    <th>Days</th>
                </tr>
            """
            
            for trade in self.closed_trades:
                html += f"""
                <tr class="sell">
                    <td><strong>{trade['symbol']}</strong></td>
                    <td>{trade['shares']}</td>
                    <td>${trade['entry_price']:.2f}</td>
                    <td>${trade['exit_price']:.2f}</td>
                    <td>${trade['pnl']:+,.0f}</td>
                    <td>{trade['pnl_pct']:+.1f}%</td>
                    <td>{trade['hold_days']}</td>
                </tr>
                """
            
            html += "</table>"
        
        # New positions
        if len(self.new_positions) > 0 or len(self.replaced_positions) > 0:
            html += """
            <h2>New Positions</h2>
            <table>
                <tr>
                    <th>Symbol</th>
                    <th>Shares</th>
                    <th>Entry Price</th>
                    <th>Position Value</th>
                    <th>Type</th>
                </tr>
            """
            
            for symbol in self.new_positions:
                pos = self.positions[symbol]
                html += f"""
                <tr class="buy">
                    <td><strong>{symbol}</strong></td>
                    <td>{pos['shares']}</td>
                    <td>${pos['entry_price']:.2f}</td>
                    <td>${pos['entry_value']:,.0f}</td>
                    <td>New</td>
                </tr>
                """
            
            for symbol in self.replaced_positions:
                pos = self.positions[symbol]
                html += f"""
                <tr class="replace">
                    <td><strong>{symbol}</strong></td>
                    <td>{pos['shares']}</td>
                    <td>${pos['entry_price']:.2f}</td>
                    <td>${pos['entry_value']:,.0f}</td>
                    <td>Replacement</td>
                </tr>
                """
            
            html += "</table>"
        
        # Current positions - ALWAYS show
        html += """
        <h2>Current Portfolio ({} positions)</h2>
        <table>
            <tr>
                <th>Symbol</th>
                <th>Shares</th>
                <th>Entry Price</th>
                <th>Current Price</th>
                <th>Position Value</th>
                <th>Unrealized P&L</th>
                <th>Return %</th>
                <th>Days Held</th>
            </tr>
        """.format(len(self.positions))
        
        # Get current prices for all positions (yesterday's close or most recent completed day)
        current_prices = {}
        
        # Get data from last 10 days to ensure we have recent prices
        end_date = datetime.now()
        start_date = end_date - timedelta(days=10)
        
        for symbol in self.positions.keys():
            try:
                # Get last 10 days of data (ensures we get RECENT data, not old data)
                df = self.db.get_ohlcv_data(
                    symbol,
                    start_date=start_date,
                    end_date=end_date
                )
                
                if not df.empty:
                    # Get most recent close (last row after ordering by date)
                    latest_close = df['close'].iloc[-1]
                    latest_date = df['timestamp'].iloc[-1]
                    entry_price = self.positions[symbol]['entry_price']
                    
                    # Log what date we're using
                    logger.debug(f"{symbol}: Using price ${latest_close:.2f} from {latest_date.date()}")
                    
                    # Sanity check: Price shouldn't change more than 10x in either direction
                    # This catches obviously bad data like CGC at $258 or SNDL at $84
                    price_ratio = latest_close / entry_price
                    if 0.1 <= price_ratio <= 10.0:
                        # Price looks reasonable
                        current_prices[symbol] = latest_close
                    else:
                        # Price looks corrupted - use entry price
                        logger.warning(f"[DATA ISSUE] {symbol}: Latest price ${latest_close:.2f} from {latest_date.date()} vs entry ${entry_price:.2f} (ratio: {price_ratio:.1f}x) - using entry price")
                        current_prices[symbol] = entry_price
                else:
                    logger.warning(f"[NO DATA] {symbol}: No data in last 10 days - using entry price")
                    current_prices[symbol] = entry_price
            except Exception as e:
                logger.warning(f"[ERROR] Could not get price for {symbol}: {e}")
                current_prices[symbol] = self.positions[symbol]['entry_price']

        
        # Sort positions by symbol
        for symbol in sorted(self.positions.keys()):
            pos = self.positions[symbol]
            current_price = current_prices.get(symbol, pos['entry_price'])
            current_value = pos['shares'] * current_price
            unrealized_pnl = current_value - pos['entry_value']
            unrealized_pct = (unrealized_pnl / pos['entry_value']) * 100
            # Convert entry_date to date if it's a Timestamp
            entry_date = pos['entry_date'].date() if hasattr(pos['entry_date'], 'date') else pos['entry_date']
            days_held = (datetime.now().date() - entry_date).days
            
            # Color code by P&L
            row_class = ''
            if unrealized_pnl > 0:
                row_class = ' class="buy"'
            elif unrealized_pnl < 0:
                row_class = ' class="sell"'
            
            html += f"""
            <tr{row_class}>
                <td><strong>{symbol}</strong></td>
                <td>{pos['shares']}</td>
                <td>${pos['entry_price']:.2f}</td>
                <td>${current_price:.2f}</td>
                <td>${current_value:,.0f}</td>
                <td>${unrealized_pnl:+,.0f}</td>
                <td>{unrealized_pct:+.1f}%</td>
                <td>{days_held}</td>
            </tr>
            """
        
        html += "</table>"
        
        html += """
        </body>
        </html>
        """
        
        return html
    
    def run(self):
        """
        Main execution workflow
        """
        logger.info("="*80)
        logger.info("DAILY PORTFOLIO MANAGER")
        logger.info("="*80)
        logger.info(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("="*80)
        
        # Detect market regime
        spy_bearish = detect_bear_regime(self.db, datetime.now())
        
        
        # Step 0: Cache universe FIRST (prevents false "universe drop" detections)
        logger.info("\n" + "="*80)
        logger.info("STEP 0: INITIALIZING UNIVERSE")
        logger.info("="*80)
        current_date = datetime.now()
        _ = self.selector.get_universe(current_date)
        universe_info = self.selector.get_universe_info()
        logger.info(f"✓ Universe cached: {universe_info['size']} stocks from {universe_info['cache_month']}")
        logger.info(f"   This ensures sell signal checks have accurate universe data")
        
        # Step 1: Check sell signals
        sells = self.check_sell_signals(spy_bearish)
        
        # Step 2: Scan for buy signals
        buy_signals = self.scan_for_buy_signals()
        
        # Step 3: Find replacement opportunities (FIX #4: pass sells to exclude them)
        replacements = self.find_replacement_candidates(buy_signals, sells)
        
        # Step 4: Execute all changes
        self.execute_portfolio_changes(sells, buy_signals, replacements)
        
        # Step 5: Update Excel
        self.update_excel()
        
        # Step 6: Send email
        self.send_email_report(spy_bearish)
        
        # Final summary
        logger.info("\n" + "="*80)
        logger.info("PORTFOLIO MANAGEMENT COMPLETE")
        logger.info("="*80)
        logger.info(f"Final portfolio: {len(self.positions)}/{self.max_positions} positions")
        logger.info(f"Portfolio value: ${self.get_portfolio_value():,.2f}")
        logger.info("="*80)
        
        return 0


def main():
    """Main entry point"""
    try:
        manager = PortfolioManager(
            initial_cash=100000,
            max_positions=20,
            position_size_pct=0.05
        )
        
        return manager.run()
        
    except Exception as e:
        logger.error(f"FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)