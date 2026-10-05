"""
Daily Portfolio Manager - MOMENTUM UNIVERSE EDITION
====================================================
Generates the next session's orders from the latest close, using the same
decision engine as backtest.py (strategy.plan_day).

State:
- portfolio_state.json is the ledger (cash + positions). It is written
  atomically BEFORE the Excel tracker or email, so a locked/missing tracker
  can never lose positions.
- universe_cache.json keeps the monthly momentum universe between runs.
- On first run the ledger is migrated from trade_tracker.xlsx
  (Current Positions sheet + realized P&L computed from Trade Log values).

Safety:
- Refuses to run twice for the same data date (use --force to override)
- Signals are only generated from bars dated on the latest SPY date
- --dry-run computes and reports orders without saving anything

Run after market close once the data update has completed:
    python daily_portfolio_manager.py [--dry-run] [--force]
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import argparse
import json
import logging
import os
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

import pandas as pd

import config
from logging_setup import setup_logging
from strategy import fill_price, plan_day, shares_for, symbol_signal

PROJECT_ROOT = Path(__file__).resolve().parent
STATE_FILE = PROJECT_ROOT / 'portfolio_state.json'
UNIVERSE_CACHE_FILE = PROJECT_ROOT / 'universe_cache.json'
TRACKER_FILE = PROJECT_ROOT / 'trade_tracker.xlsx'
REPORT_FILE = PROJECT_ROOT / 'daily_orders.html'

TRADE_LOG_HEADERS = [
    'Trade #', 'Entry Date', 'Exit Date', 'Symbol', 'Action', 'Shares', 'Entry Price', 'Exit Price',
    'Entry Value', 'Exit Value', 'Gross P&L', 'Commission', 'Net P&L', 'Return %', 'Hold Days',
    'Win/Loss', 'Strategy', 'Market Regime', 'Exit Type',
]

logger = logging.getLogger('portfolio_manager')


# ============================================================================
# LEDGER
# ============================================================================

def load_state(initial_cash: float) -> dict:
    """Load the ledger, migrating from the Excel tracker on first run"""
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text())
        for pos in state['positions'].values():
            pos['entry_date'] = pd.Timestamp(pos['entry_date'])
        return state

    logger.warning("No %s found - migrating from %s", STATE_FILE.name, TRACKER_FILE.name)
    positions, realized = {}, 0.0
    if TRACKER_FILE.exists():
        positions, realized = _read_tracker(TRACKER_FILE)
    invested = sum(p['cost_basis'] for p in positions.values())
    cash = initial_cash + realized - invested
    logger.warning(
        "Migrated %d positions; cash = %.2f initial + %.2f realized - %.2f invested = %.2f. "
        "VERIFY THIS AGAINST YOUR BROKER and edit %s if it differs.",
        len(positions), initial_cash, realized, invested, cash, STATE_FILE.name
    )
    return {'cash': cash, 'positions': positions, 'last_run_data_date': None,
            'initial_cash': initial_cash}


def _read_tracker(path: Path):
    """Positions and realized P&L from tracker VALUES (formula cells are ignored)"""
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=False)

    realized = 0.0
    for row in wb['Trade Log'].iter_rows(min_row=2, values_only=True):
        symbol, shares, entry_px, exit_px, commission = row[3], row[5], row[6], row[7], row[11]
        if not symbol or not all(isinstance(v, (int, float)) for v in (shares, entry_px, exit_px)):
            continue
        realized += shares * (exit_px - entry_px) - (commission if isinstance(commission, (int, float)) else 0)

    positions = {}
    for row in wb['Current Positions'].iter_rows(min_row=2, values_only=True):
        symbol, shares, entry_px, entry_date = row[0], row[1], row[2], row[3]
        if not symbol or not isinstance(shares, (int, float)) or not isinstance(entry_px, (int, float)):
            continue
        positions[str(symbol)] = {
            'shares': int(shares),
            'entry_price': float(entry_px),
            'cost_basis': float(entry_px) * int(shares),
            'entry_date': pd.Timestamp(entry_date),
        }
    return positions, realized


def save_state(state: dict):
    """Atomic write so a crash can never leave a half-written ledger"""
    serializable = dict(state)
    serializable['positions'] = {
        sym: {**pos, 'entry_date': pd.Timestamp(pos['entry_date']).strftime('%Y-%m-%d')}
        for sym, pos in state['positions'].items()
    }
    tmp = STATE_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(serializable, indent=2))
    tmp.replace(STATE_FILE)
    logger.info(f"Saved ledger: {len(state['positions'])} positions, cash ${state['cash']:,.2f}")


# ============================================================================
# PORTFOLIO MANAGER
# ============================================================================

class PortfolioManager:
    """Runs the daily decision cycle against the ledger"""

    def __init__(self, db, initial_cash=100000):
        from universe_selector import UniverseSelector

        self.db = db
        self.state = load_state(initial_cash)
        self.selector = UniverseSelector(
            self.db,
            exclude_symbols=['SPY'],
            cache_file=UNIVERSE_CACHE_FILE,
        )
        self.closed_trades = []
        self.new_positions = []
        self.replaced_positions = []
        self.prices = {}

    @property
    def positions(self):
        return self.state['positions']

    def latest_data_date(self) -> pd.Timestamp:
        now = datetime.now()
        spy = self.db.get_ohlcv_data('SPY', start_date=now - timedelta(days=14), end_date=now)
        if spy.empty:
            raise RuntimeError("No SPY data in the last 14 days - run daily_update.py first")
        return pd.Timestamp(spy['timestamp'].max()).normalize()

    def load_signals(self, symbols, data_date):
        """Signals for symbols whose latest bar is data_date; stale symbols are reported and skipped"""
        start = data_date - timedelta(days=config.INDICATOR_LOOKBACK_DAYS)
        end = data_date + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)  # whole day, never the next
        signals, stale = {}, []
        for symbol in sorted(symbols):
            try:
                df = self.db.get_ohlcv_data(symbol, start_date=start, end_date=end)
            except Exception:
                logger.exception("%s: failed to load data", symbol)
                continue
            if df.empty:
                stale.append(symbol)
                continue
            self.prices[symbol] = float(df['close'].iloc[-1])
            if pd.Timestamp(df['timestamp'].iloc[-1]).normalize() != data_date:
                stale.append(symbol)
                continue
            sig = symbol_signal(symbol, df)
            if sig is not None:
                signals[symbol] = sig
        if stale:
            logger.warning("%d symbols have no bar for %s (skipped): %s",
                           len(stale), data_date.date(), ', '.join(stale[:20]))
        return signals

    def equity(self) -> float:
        return self.state['cash'] + sum(
            pos['shares'] * self.prices.get(sym, pos['entry_price'])
            for sym, pos in self.positions.items()
        )

    def _close(self, symbol, data_date, exit_type, spy_bearish):
        pos = self.positions.pop(symbol)
        price = self.prices.get(symbol, pos['entry_price'])
        px = fill_price(price, 'SELL')
        proceeds = pos['shares'] * px - config.COMMISSION
        self.state['cash'] += proceeds
        pnl = proceeds - pos['cost_basis']
        trade = {
            'symbol': symbol,
            'entry_date': pd.Timestamp(pos['entry_date']),
            'exit_date': data_date,
            'shares': pos['shares'],
            'entry_price': pos['entry_price'],
            'exit_price': px,
            'pnl': pnl,
            'pnl_pct': pnl / pos['cost_basis'] * 100 if pos['cost_basis'] else 0.0,
            'hold_days': (data_date - pd.Timestamp(pos['entry_date'])).days,
            'regime': 'BEAR' if spy_bearish else 'BULL',
            'exit_type': exit_type,
        }
        self.closed_trades.append(trade)
        logger.info(f"  [SELL {exit_type}] {symbol}: {trade['shares']} @ ~${px:.2f}, "
                    f"P&L ${pnl:+,.0f} ({trade['pnl_pct']:+.1f}%)")

    def _open(self, symbol, data_date, equity) -> bool:
        if symbol in self.positions:
            logger.warning("  [SKIP] %s already held", symbol)
            return False
        px = fill_price(self.prices[symbol], 'BUY')
        shares = shares_for(equity, px, self.state['cash'])
        if shares <= 0:
            logger.warning(f"  [SKIP] {symbol}: insufficient cash (${self.state['cash']:,.2f})")
            return False
        cost = shares * px + config.COMMISSION
        self.state['cash'] -= cost
        self.positions[symbol] = {
            'shares': shares,
            'entry_price': px,
            'cost_basis': cost,
            'entry_date': data_date,
        }
        logger.info(f"  [BUY] {symbol}: {shares} @ ~${px:.2f} (${cost:,.0f})")
        return True

    def run(self, force=False, dry_run=False) -> int:
        from protection.market_regime import detect_bear_regime

        logger.info("=" * 80)
        logger.info("DAILY PORTFOLIO MANAGER%s", " (DRY RUN)" if dry_run else "")
        logger.info("=" * 80)

        data_date = self.latest_data_date()
        last_run = self.state.get('last_run_data_date')
        logger.info("Latest data: %s | last run: %s", data_date.date(), last_run)
        if last_run == data_date.strftime('%Y-%m-%d') and not force:
            logger.warning("Already ran for %s - orders were generated. Use --force to rerun.", data_date.date())
            return 0

        spy_bearish = detect_bear_regime(self.db, data_date)
        logger.info("Market regime: %s", 'BEAR (FastExit)' if spy_bearish else 'BULL (Normal)')

        universe = self.selector.get_universe(data_date)
        if not universe:
            logger.error("Universe is empty - no trading today")
            return 1

        signals = self.load_signals(set(universe) | set(self.positions), data_date)
        for sym in self.positions:
            if sym not in signals:
                logger.warning("  %s is held but has no current signal - holding unchanged", sym)

        plan = plan_day(self.positions, signals, spy_bearish, universe)
        logger.info("Plan: %d sells, %d replacements, %d buys, %d unfilled buy signals",
                    len(plan.sells), len(plan.replacements), len(plan.buys), plan.missed_signals)

        for order in plan.sells:
            self._close(order['symbol'], data_date, order['reason'], spy_bearish)
        for rep in plan.replacements:
            logger.info("  [REPLACE] %s => %s (+%.0f%% strength)",
                        rep['sell_symbol'], rep['buy_symbol'], rep['improvement'] * 100)
            self._close(rep['sell_symbol'], data_date, 'Replacement', spy_bearish)
        equity = self.equity()
        for rep in plan.replacements:
            if self._open(rep['buy_symbol'], data_date, equity):
                self.replaced_positions.append(rep['buy_symbol'])
        for symbol in plan.buys:
            if self._open(symbol, data_date, equity):
                self.new_positions.append(symbol)

        logger.info(f"Positions: {len(self.positions)}/{config.MAX_POSITIONS} | "
                    f"cash ${self.state['cash']:,.2f} | equity ${self.equity():,.2f}")

        html = self.generate_html_report(spy_bearish, data_date)
        if dry_run:
            logger.info("Dry run - ledger, tracker and email untouched")
            REPORT_FILE.with_name('daily_orders_dryrun.html').write_text(html, encoding='utf-8')
            return 0

        self.state['last_run_data_date'] = data_date.strftime('%Y-%m-%d')
        save_state(self.state)          # ledger first - never lost to an Excel failure
        self.update_excel()
        REPORT_FILE.write_text(html, encoding='utf-8')
        logger.info("Saved report to %s", REPORT_FILE.name)
        self.send_email_report(html, data_date)
        return 0

    # ------------------------------------------------------------------ Excel

    def update_excel(self):
        """Append closed trades and rewrite Current Positions (values, not formulas)"""
        try:
            from openpyxl import Workbook, load_workbook
            if TRACKER_FILE.exists():
                wb = load_workbook(TRACKER_FILE)
            else:
                logger.info("Creating %s", TRACKER_FILE.name)
                wb = Workbook()
                wb.active.title = 'Trade Log'
                wb['Trade Log'].append(TRADE_LOG_HEADERS)
                wb.create_sheet('Current Positions')
            self._append_trades(wb['Trade Log'])
            self._write_positions(wb['Current Positions'])
            wb.save(TRACKER_FILE)
            logger.info("Excel tracker updated (%d trades added)", len(self.closed_trades))
        except PermissionError:
            logger.error("Cannot write %s - is it open in Excel? Ledger is saved; "
                         "rerun with --force after closing Excel to update the tracker.", TRACKER_FILE.name)
        except Exception:
            logger.exception("Excel update failed - ledger is saved, tracker NOT updated")

    def _append_trades(self, ws):
        last = 1
        for row in range(ws.max_row, 0, -1):
            value = ws.cell(row=row, column=4).value
            if value is not None and str(value).strip():
                last = row
                break
        for offset, t in enumerate(self.closed_trades, 1):
            r = last + offset
            entry_value = t['shares'] * t['entry_price']
            exit_value = t['shares'] * t['exit_price']
            commission = 2 * config.COMMISSION
            net = exit_value - entry_value - commission
            values = {
                'A': r - 1,
                'B': t['entry_date'].to_pydatetime(), 'C': t['exit_date'].to_pydatetime(),
                'D': t['symbol'], 'E': 'LONG', 'F': t['shares'],
                'G': t['entry_price'], 'H': t['exit_price'],
                'I': entry_value, 'J': exit_value, 'K': exit_value - entry_value,
                'L': commission, 'M': net, 'N': net / entry_value if entry_value else 0,
                'O': t['hold_days'], 'P': 'Win' if net > 0 else 'Loss',
                'Q': 'VPVMA', 'R': t['regime'], 'S': t['exit_type'],
            }
            for col, value in values.items():
                ws[f'{col}{r}'] = value

    def _write_positions(self, ws):
        headers = ['Symbol', 'Shares', 'Entry Price', 'Entry Date', 'Current Price',
                   'Entry Value', 'Current Value', 'Unrealized P&L', 'Unrealized %']
        for row in range(2, ws.max_row + 1):
            for col in range(1, len(headers) + 1):
                ws.cell(row=row, column=col).value = None
        for col, header in enumerate(headers, 1):
            ws.cell(row=1, column=col).value = header
        for r, (symbol, pos) in enumerate(sorted(self.positions.items()), 2):
            price = self.prices.get(symbol, pos['entry_price'])
            value = price * pos['shares']
            row = [symbol, pos['shares'], pos['entry_price'], pd.Timestamp(pos['entry_date']).to_pydatetime(),
                   price, pos['cost_basis'], value, value - pos['cost_basis'],
                   (value / pos['cost_basis'] - 1) if pos['cost_basis'] else 0]
            for col, v in enumerate(row, 1):
                ws.cell(row=r, column=col).value = v

    # ------------------------------------------------------------- reporting

    def send_email_report(self, html, data_date):
        email_user = os.getenv('EMAIL_USER')
        email_pass = os.getenv('EMAIL_PASS')
        email_to = os.getenv('EMAIL_TO')
        if not all([email_user, email_pass, email_to]):
            logger.info("Email not configured (EMAIL_USER/EMAIL_PASS/EMAIL_TO) - skipped")
            return
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"VPVMA Trading Orders - {data_date.strftime('%Y-%m-%d')} close"
        msg['From'] = email_user
        msg['To'] = email_to
        msg.attach(MIMEText(html, 'html'))
        try:
            with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=30) as server:
                server.login(email_user, email_pass)
                server.sendmail(email_user, email_to, msg.as_string())
            logger.info("Email sent to %s", email_to)
        except Exception:
            logger.exception("Email failed")

    def generate_html_report(self, spy_bearish, data_date):
        rows_closed = ''.join(
            f"<tr class='sell'><td><strong>{escape(t['symbol'])}</strong></td><td>SELL</td>"
            f"<td>{t['shares']}</td><td>${t['exit_price']:.2f}</td><td>${t['pnl']:+,.0f}</td>"
            f"<td>{t['pnl_pct']:+.1f}%</td><td>{t['hold_days']}</td><td>{escape(t['exit_type'])}</td></tr>"
            for t in self.closed_trades
        )
        rows_new = ''.join(
            f"<tr class='{cls}'><td><strong>{escape(sym)}</strong></td><td>BUY</td>"
            f"<td>{self.positions[sym]['shares']}</td><td>${self.positions[sym]['entry_price']:.2f}</td>"
            f"<td>${self.positions[sym]['cost_basis']:,.0f}</td><td>{label}</td></tr>"
            for syms, cls, label in ((self.new_positions, 'buy', 'New'),
                                     (self.replaced_positions, 'replace', 'Replacement'))
            for sym in syms
        )
        rows_held = ''
        for sym, pos in sorted(self.positions.items()):
            price = self.prices.get(sym, pos['entry_price'])
            pnl = price * pos['shares'] - pos['cost_basis']
            pct = pnl / pos['cost_basis'] * 100 if pos['cost_basis'] else 0
            cls = 'buy' if pnl > 0 else 'sell' if pnl < 0 else ''
            days = (data_date - pd.Timestamp(pos['entry_date'])).days
            rows_held += (f"<tr class='{cls}'><td><strong>{escape(sym)}</strong></td><td>{pos['shares']}</td>"
                          f"<td>${pos['entry_price']:.2f}</td><td>${price:.2f}</td>"
                          f"<td>${price * pos['shares']:,.0f}</td><td>${pnl:+,.0f}</td>"
                          f"<td>{pct:+.1f}%</td><td>{days}</td></tr>")

        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
body {{ font-family: Arial, sans-serif; margin: 20px; }}
h1 {{ color: #2c3e50; }} h2 {{ color: #34495e; margin-top: 30px; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 10px; }}
th {{ background-color: #3498db; color: white; padding: 12px; text-align: left; }}
td {{ padding: 10px; border-bottom: 1px solid #ddd; }}
.sell {{ background-color: #ffe6e6; }} .buy {{ background-color: #e6ffe6; }} .replace {{ background-color: #fff4e6; }}
.metric {{ display: inline-block; margin: 10px 20px; }}
.metric-label {{ color: #7f8c8d; }} .metric-value {{ font-size: 24px; font-weight: bold; color: #2c3e50; }}
</style></head><body>
<h1>VPVMA Orders for the Next Session</h1>
<p><strong>Signals from close of:</strong> {data_date.strftime('%Y-%m-%d (%A)')}</p>
<p><strong>Market Regime:</strong> {'BEAR (FastExit Active)' if spy_bearish else 'BULL (Normal)'}</p>
<p><em>Prices are estimates from the last close; place orders at the next open and record actual fills.</em></p>
<div class="metric"><div class="metric-label">Portfolio Value</div><div class="metric-value">${self.equity():,.0f}</div></div>
<div class="metric"><div class="metric-label">Positions</div><div class="metric-value">{len(self.positions)}/{config.MAX_POSITIONS}</div></div>
<div class="metric"><div class="metric-label">Cash</div><div class="metric-value">${self.state['cash']:,.0f}</div></div>
<h2>Sell Orders</h2>
<table><tr><th>Symbol</th><th>Side</th><th>Shares</th><th>Est. Price</th><th>P&amp;L</th><th>Return</th><th>Days</th><th>Reason</th></tr>
{rows_closed or '<tr><td colspan="8">None</td></tr>'}</table>
<h2>Buy Orders</h2>
<table><tr><th>Symbol</th><th>Side</th><th>Shares</th><th>Est. Price</th><th>Cost</th><th>Type</th></tr>
{rows_new or '<tr><td colspan="6">None</td></tr>'}</table>
<h2>Portfolio After Orders ({len(self.positions)} positions)</h2>
<table><tr><th>Symbol</th><th>Shares</th><th>Entry</th><th>Last Close</th><th>Value</th><th>Unrealized P&amp;L</th><th>Return</th><th>Days</th></tr>
{rows_held}</table>
</body></html>"""


def main():
    parser = argparse.ArgumentParser(description='Generate VPVMA orders from the latest close')
    parser.add_argument('--dry-run', action='store_true', help='Compute orders without saving anything')
    parser.add_argument('--force', action='store_true', help='Run even if already run for this data date')
    args = parser.parse_args()

    setup_logging('portfolio_manager')
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / '.env')
    except ImportError:
        pass

    from data.database import Database
    try:
        manager = PortfolioManager(Database(),
                                   initial_cash=100000)
        return manager.run(force=args.force, dry_run=args.dry_run)
    except Exception:
        logger.exception("FATAL ERROR")
        return 1


if __name__ == "__main__":
    sys.exit(main())
