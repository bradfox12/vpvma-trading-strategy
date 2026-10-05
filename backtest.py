"""
VPVMA Backtest with FastExit+SPY200 Protection

Uses the same decision engine as live trading (strategy.plan_day), so entry,
exit, universe and replacement rules cannot drift between the two.

Execution model:
- Signals are computed at the close of day t
- Orders fill at the OPEN of the symbol's next bar (no same-close fills)
- Slippage and commission from config
- Held symbols whose data stops (delisting, ticker change) are force-sold at
  their last close after DELIST_GRACE_DAYS trading days without a bar

Indicators are computed once per symbol over the full loaded history; values at
day t only use bars up to t, so there is no look-ahead.

Run from project directory:
    python backtest.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import logging
from datetime import timedelta
from typing import Dict, Optional

import numpy as np
import pandas as pd

import config
from protection.market_regime import bear_regime_series
from strategy import (
    compute_indicator_frame,
    fill_price,
    plan_day,
    rank_by_momentum,
    shares_for,
    SymbolSignal,
)

logger = logging.getLogger(__name__)

DELIST_GRACE_DAYS = 5
PANEL_COLUMNS = ['open', 'close', 'vpvma', 'vpvmas', 'vpvma_prev', 'vpvmas_prev', 'buy_signal', 'strength']


class ProtectedPortfolio:
    """Cash, positions and trade/equity records for one backtest"""

    def __init__(self, initial_capital=100000, max_positions=None):
        self.initial_capital = initial_capital
        self.cash = float(initial_capital)
        self.max_positions = max_positions or config.MAX_POSITIONS

        self.positions = {}
        self.history = []
        self.trades = []

        self.protection_active = False
        self.protection_days = 0
        self.total_days = 0

        self.total_buy_signals = 0
        self.missed_signals = 0
        self.fastexit_sells = 0
        self.normal_sells = 0

    def equity(self, marks: Dict[str, float]) -> float:
        return self.cash + sum(pos['shares'] * marks.get(sym, pos['entry_price'])
                               for sym, pos in self.positions.items())

    def buy(self, symbol, price, date, equity, strength=0.0):
        if symbol in self.positions or len(self.positions) >= self.max_positions:
            return False
        px = fill_price(price, 'BUY')
        shares = shares_for(equity, px, self.cash)
        if shares <= 0:
            return False
        cost = shares * px + config.COMMISSION
        self.cash -= cost
        self.positions[symbol] = {
            'shares': shares,
            'entry_price': px,
            'cost_basis': cost,
            'entry_date': date,
            'strength': strength,
        }
        self.trades.append({
            'date': date, 'symbol': symbol, 'action': 'BUY', 'shares': shares,
            'price': px, 'commission': config.COMMISSION,
            'protection_active': self.protection_active,
        })
        return True

    def sell(self, symbol, price, date, reason='Signal', fast_exit=False):
        pos = self.positions.pop(symbol, None)
        if pos is None:
            return False
        px = fill_price(price, 'SELL')
        proceeds = pos['shares'] * px - config.COMMISSION
        self.cash += proceeds
        self.trades.append({
            'date': date, 'symbol': symbol, 'action': 'SELL', 'shares': pos['shares'],
            'price': px, 'commission': config.COMMISSION,
            'pnl': proceeds - pos['cost_basis'],
            'hold_days': (date - pos['entry_date']).days,
            'protection_active': self.protection_active,
            'fast_exit': fast_exit,
            'exit_reason': reason,
        })
        if fast_exit:
            self.fastexit_sells += 1
        else:
            self.normal_sells += 1
        return True


def build_panels(frames: Dict[str, pd.DataFrame], trading_days: pd.DatetimeIndex) -> Dict[str, pd.DataFrame]:
    """Align every symbol's indicator frame to the trading calendar: column -> (day × symbol)"""
    indicator = {sym: compute_indicator_frame(df) for sym, df in frames.items() if len(df) > 0}
    panels = {}
    for col in PANEL_COLUMNS:
        panels[col] = pd.DataFrame(
            {sym: f[col].reindex(trading_days) for sym, f in indicator.items()},
            index=trading_days,
        )
    panels['last_bar'] = pd.Series({sym: f.index.max() for sym, f in indicator.items()})
    panels['closes'] = {sym: f['close'] for sym, f in indicator.items()}
    return panels


def run_backtest_on_frames(
    frames: Dict[str, pd.DataFrame],
    spy_data: pd.DataFrame,
    start_date,
    end_date,
    initial_capital: float = 100000,
    universe_size: Optional[int] = None,
    momentum_period: Optional[int] = None,
) -> dict:
    """
    Backtest on in-memory OHLCV frames (no database access).

    Args:
        frames: symbol -> DataFrame[timestamp, open, high, low, close, volume]
                (include history before start_date for indicator warmup)
        spy_data: SPY OHLCV; defines the trading calendar and the regime
        start_date, end_date: Evaluation period
        initial_capital: Starting cash
        universe_size: Top-N momentum universe re-selected monthly; None trades every symbol
        momentum_period: Momentum lookback in bars (default config.MOMENTUM_PERIOD)
    """
    start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
    momentum_period = momentum_period or config.MOMENTUM_PERIOD

    spy_data = spy_data.sort_values('timestamp').reset_index(drop=True)
    regime = bear_regime_series(spy_data)
    trading_days = pd.DatetimeIndex(spy_data['timestamp'])
    trading_days = trading_days[(trading_days >= start) & (trading_days <= end)]
    if len(trading_days) == 0:
        raise ValueError(f"No SPY trading days between {start.date()} and {end.date()}")

    logger.info("Computing indicators for %d symbols...", len(frames))
    panels = build_panels(frames, trading_days)
    symbols = list(panels['open'].columns)

    portfolio = ProtectedPortfolio(initial_capital=initial_capital)
    marks: Dict[str, float] = {}
    pending = None
    pending_strength = {}
    universe = None
    universe_month = None
    universe_history = []
    day_pos = {d: i for i, d in enumerate(trading_days)}

    total_days = len(trading_days)
    step = max(1, total_days // 20)

    for i, date in enumerate(trading_days):
        if i % step == 0:
            logger.info("Progress: %d%% (%s)", int(i / total_days * 100), date.date())

        opens = panels['open'].loc[date]
        closes = panels['close'].loc[date]

        # 1. Fill yesterday's orders at today's open
        unfilled_sells = []
        if pending is not None:
            exits = pending.sells + [{'symbol': r['sell_symbol'], 'reason': 'Replacement', 'fast_exit': False}
                                     for r in pending.replacements]
            for order in exits:
                sym = order['symbol']
                px = opens.get(sym)
                if px is None or np.isnan(px):
                    unfilled_sells.append(order)  # no bar today - retry at the next bar
                    continue
                portfolio.sell(sym, px, date, order['reason'], order['fast_exit'])
            equity = portfolio.equity(marks)
            buy_list = [r['buy_symbol'] for r in pending.replacements] + pending.buys
            for sym in buy_list:
                px = opens.get(sym)
                if px is None or np.isnan(px):
                    portfolio.missed_signals += 1
                    continue
                portfolio.buy(sym, px, date, equity, pending_strength.get(sym, 0.0))

        # 2. Mark to market
        for sym, px in closes.dropna().items():
            marks[sym] = float(px)

        # 3. Force-exit positions whose data has stopped
        for sym in list(portfolio.positions):
            last_bar = panels['last_bar'].get(sym)
            if last_bar is not None and last_bar < date:
                bars_since = i - day_pos.get(last_bar, i - DELIST_GRACE_DAYS - 1)
                if last_bar not in day_pos or bars_since > DELIST_GRACE_DAYS:
                    logger.warning("%s: no data since %s - closing at last close %.2f",
                                   sym, last_bar.date(), marks.get(sym, np.nan))
                    portfolio.sell(sym, marks.get(sym, portfolio.positions[sym]['entry_price']),
                                   date, 'No Data')

        # 4. Regime
        bearish = bool(regime.asof(date)) if len(regime) else False
        portfolio.protection_active = bearish and config.ENABLE_BEAR_PROTECTION
        portfolio.total_days += 1
        portfolio.protection_days += int(portfolio.protection_active)

        # 5. Monthly momentum universe
        if universe_size is not None and date.strftime('%Y-%m') != universe_month:
            ranked = rank_by_momentum(panels['closes'], date, momentum_period, universe_size)
            universe = ranked['symbol'].tolist()
            universe_month = date.strftime('%Y-%m')
            universe_history.append({'date': date, 'symbols': universe})

        # 6. Today's signals
        signals = {}
        valid = panels['vpvmas'].loc[date].notna() & panels['vpvma'].loc[date].notna()
        for sym in valid[valid].index:
            signals[sym] = SymbolSignal(
                symbol=sym,
                price=float(closes[sym]),
                vpvma=float(panels['vpvma'].at[date, sym]),
                vpvmas=float(panels['vpvmas'].at[date, sym]),
                vpvma_prev=float(panels['vpvma_prev'].at[date, sym]),
                vpvmas_prev=float(panels['vpvmas_prev'].at[date, sym]),
                buy_signal=bool(panels['buy_signal'].at[date, sym]),
                strength=float(panels['strength'].at[date, sym]),
            )
        portfolio.total_buy_signals += sum(
            1 for s in signals.values()
            if s.buy_signal and (universe is None or s.symbol in universe)
        )

        # 7. Decide tomorrow's orders
        pending = plan_day(portfolio.positions, signals, portfolio.protection_active, universe)
        planned = {o['symbol'] for o in pending.sells} | {r['sell_symbol'] for r in pending.replacements}
        pending.sells += [o for o in unfilled_sells
                          if o['symbol'] in portfolio.positions and o['symbol'] not in planned]
        pending_strength = {s: signals[s].strength for s in pending.buys}
        pending_strength.update({r['buy_symbol']: signals[r['buy_symbol']].strength
                                 for r in pending.replacements})
        portfolio.missed_signals += pending.missed_signals

        portfolio.history.append({
            'date': date,
            'equity': portfolio.equity(marks),
            'cash': portfolio.cash,
            'num_positions': len(portfolio.positions),
            'protection_active': portfolio.protection_active,
        })

    df_history = pd.DataFrame(portfolio.history)
    df_trades = pd.DataFrame(portfolio.trades, columns=[
        'date', 'symbol', 'action', 'shares', 'price', 'commission', 'pnl',
        'hold_days', 'protection_active', 'fast_exit', 'exit_reason'])
    metrics = compute_metrics(df_history, df_trades, initial_capital)

    return {
        'history': df_history,
        'trades': df_trades,
        'portfolio': portfolio,
        'metrics': metrics,
        'universe_history': universe_history,
    }


def compute_metrics(df_history: pd.DataFrame, df_trades: pd.DataFrame, initial_capital: float) -> dict:
    """Return/risk/trade statistics; adds cummax, drawdown and returns columns to df_history"""
    final_equity = df_history['equity'].iloc[-1]
    total_return = (final_equity / initial_capital - 1) * 100
    years = (df_history['date'].iloc[-1] - df_history['date'].iloc[0]).days / 365.25
    cagr = ((final_equity / initial_capital) ** (1 / years) - 1) * 100 if years > 0 else np.nan

    df_history['cummax'] = df_history['equity'].cummax()
    df_history['drawdown'] = (df_history['equity'] / df_history['cummax'] - 1) * 100
    max_dd = df_history['drawdown'].min()

    returns = df_history['equity'].pct_change()
    df_history['returns'] = returns
    r = returns.dropna()
    std = r.std()
    annual_vol = std * np.sqrt(252) * 100 if len(r) > 1 else np.nan
    sharpe = r.mean() / std * np.sqrt(252) if std and std > 0 else np.nan
    downside_dev = np.sqrt((np.minimum(r, 0) ** 2).mean()) if len(r) else 0
    sortino = r.mean() / downside_dev * np.sqrt(252) if downside_dev > 0 else np.nan
    losses = -r[r < 0].sum()
    omega = r[r > 0].sum() / losses if losses > 0 else np.nan
    calmar = cagr / abs(max_dd) if max_dd < 0 else np.nan

    sells = df_trades[df_trades['action'] == 'SELL']
    wins = sells[sells['pnl'] > 0]
    loss_trades = sells[sells['pnl'] <= 0]
    gross_loss = -loss_trades['pnl'].sum()

    return {
        'total_return': total_return,
        'cagr': cagr,
        'final_equity': final_equity,
        'sharpe': sharpe,
        'sortino': sortino,
        'omega': omega,
        'calmar': calmar,
        'max_dd': max_dd,
        'annual_vol': annual_vol,
        'num_trades': len(df_trades),
        'num_round_trips': len(sells),
        'win_rate': len(wins) / len(sells) * 100 if len(sells) else np.nan,
        'avg_win': wins['pnl'].mean() if len(wins) else np.nan,
        'avg_loss': loss_trades['pnl'].mean() if len(loss_trades) else np.nan,
        'profit_factor': wins['pnl'].sum() / gross_loss if gross_loss > 0 else np.nan,
        'avg_hold_days': sells['hold_days'].mean() if len(sells) else np.nan,
        'unique_symbols': df_trades['symbol'].nunique(),
    }


def load_frames(db, symbols, start_date, end_date) -> Dict[str, pd.DataFrame]:
    """Load OHLCV for every symbol once, with indicator warmup history"""
    load_start = pd.Timestamp(start_date) - timedelta(days=config.INDICATOR_LOOKBACK_DAYS)
    frames = {}
    for i, sym in enumerate(symbols, 1):
        try:
            df = db.get_ohlcv_data(sym, start_date=load_start, end_date=pd.Timestamp(end_date))
        except Exception:
            logger.exception("%s: failed to load data - excluded from backtest", sym)
            continue
        if df.empty:
            logger.warning("%s: no data in range - excluded", sym)
            continue
        frames[sym] = df
        if i % 50 == 0:
            logger.info("Loaded %d/%d symbols", i, len(symbols))
    return frames


def run_backtest(
    db,
    symbols: list,
    start_date: str,
    end_date: str,
    initial_capital: int = 100000,
    universe_size: Optional[int] = None,
):
    """
    Run the VPVMA backtest against the database.

    Args:
        db: Database instance
        symbols: Candidate symbols (SPY is used for the calendar/regime only)
        start_date, end_date: Evaluation period
        initial_capital: Starting cash
        universe_size: Monthly top-N momentum universe (config.UNIVERSE_SIZE
                       matches live trading); None trades every symbol
    """
    start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
    spy_start = start - timedelta(days=config.REGIME_LOOKBACK_DAYS)
    spy_data = db.get_ohlcv_data('SPY', start_date=spy_start, end_date=end)
    frames = load_frames(db, [s for s in symbols if s != 'SPY'], start, end)
    logger.info("Universe: %d symbols with data, period %s to %s", len(frames), start.date(), end.date())

    results = run_backtest_on_frames(frames, spy_data, start, end, initial_capital, universe_size)
    log_report(results)
    return results


def log_report(results: dict):
    m = results['metrics']
    p = results['portfolio']
    lines = [
        "=" * 80,
        "BACKTEST RESULTS",
        "=" * 80,
        f"Total Return:      {m['total_return']:+.2f}%",
        f"CAGR:              {m['cagr']:.2f}%",
        f"Final Equity:      ${m['final_equity']:,.0f}",
        f"Max Drawdown:      {m['max_dd']:.2f}%",
        f"Sharpe:            {m['sharpe']:.2f}",
        f"Sortino:           {m['sortino']:.2f}",
        f"Omega:             {m['omega']:.2f}",
        f"Calmar:            {m['calmar']:.2f}",
        f"Annual Volatility: {m['annual_vol']:.2f}%",
        f"Fills:             {m['num_trades']} ({m['num_round_trips']} round trips)",
        f"Win Rate:          {m['win_rate']:.1f}%",
        f"Avg Win / Loss:    ${m['avg_win']:,.0f} / ${m['avg_loss']:,.0f}",
        f"Profit Factor:     {m['profit_factor']:.2f}",
        f"Avg Hold:          {m['avg_hold_days']:.0f} days",
        f"Open at end:       {len(p.positions)} positions",
        f"Protection ON:     {p.protection_days}/{p.total_days} days",
        f"FastExit / Normal sells: {p.fastexit_sells} / {p.normal_sells}",
        f"Missed buy signals (no slot/cash/bar): {p.missed_signals}",
        "=" * 80,
    ]
    for line in lines:
        logger.info(line)


def main():
    import argparse
    from logging_setup import setup_logging
    from data.database import Database

    parser = argparse.ArgumentParser(description='Run the VPVMA backtest')
    parser.add_argument('--start', default='2005-01-01')
    parser.add_argument('--end', help='Default: latest SPY bar in the database')
    parser.add_argument('--capital', type=float, default=100000)
    parser.add_argument('--all-symbols', action='store_true',
                        help='Trade every symbol instead of the monthly top-N momentum universe')
    parser.add_argument('--trades-csv', help='Write the trade list to this CSV file')
    args = parser.parse_args()

    setup_logging('backtest')
    db = Database()
    end = args.end or db.latest_timestamp('SPY')
    if end is None:
        logger.error("No SPY data - load history first (scripts/fetch_eod_historical.py)")
        return 1

    results = run_backtest(
        db=db,
        symbols=[s for s in db.list_symbols() if s != 'SPY'],
        start_date=args.start,
        end_date=end,
        initial_capital=args.capital,
        universe_size=None if args.all_symbols else config.UNIVERSE_SIZE,
    )
    if args.trades_csv:
        results['trades'].to_csv(args.trades_csv, index=False)
        logger.info("Trades written to %s", args.trades_csv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
