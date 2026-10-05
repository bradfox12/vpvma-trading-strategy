"""
VPVMA Backtest with FastExit+SPY200 Protection

Uses the same screen (screens.py) and decision engine (strategy.plan_day) as
live trading, so universe, entry, exit and swap rules cannot drift apart.

Pipeline:
1. Close/volume panels for every candidate symbol
2. The screen runs on the first session of each SCREEN_FREQUENCY period using
   only data public on that date -> universe per period
3. VPVMA indicators are computed only for symbols that are ever in a universe
4. Daily loop: fill yesterday's orders at today's open, mark to market,
   decide tomorrow's orders from today's close

Execution model:
- Orders fill at the OPEN of the symbol's next bar (no same-close fills)
- Slippage and commission from config
- Held symbols whose data stops (delisting, ticker change) are force-sold at
  their last close after DELIST_GRACE_DAYS trading days without a bar

Run from project directory:
    python backtest.py [--start 2005-01-01] [--end YYYY-MM-DD] [--trades-csv trades.csv]
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import logging
from datetime import timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

import config
from protection.market_regime import bear_regime_series
from screens import Screen, ScreenData, get_screen, rebalance_key
from strategy import (
    compute_indicator_frame,
    fill_price,
    plan_day,
    shares_for,
    SymbolSignal,
)

logger = logging.getLogger(__name__)

DELIST_GRACE_DAYS = 5
SIGNAL_COLUMNS = ['open', 'close', 'vpvma', 'vpvmas', 'vpvma_prev', 'vpvmas_prev', 'buy_signal', 'strength']


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


def close_volume_panels(frames: Dict[str, pd.DataFrame]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """(closes, volumes) with one column per symbol, indexed by every date any symbol traded"""
    closes = pd.DataFrame({s: f.set_index('timestamp')['close'] for s, f in frames.items()}).sort_index()
    volumes = pd.DataFrame({s: f.set_index('timestamp')['volume'] for s, f in frames.items()}).sort_index()
    return closes.astype(float), volumes.astype(float)


def rebalance_dates(trading_days: pd.DatetimeIndex, frequency: str = None) -> List[pd.Timestamp]:
    """First session of the backtest and of every new screening period"""
    keys = [rebalance_key(d, frequency) for d in trading_days]
    return [d for i, d in enumerate(trading_days) if i == 0 or keys[i] != keys[i - 1]]


def run_screens(screen: Screen, dates, closes, volumes, securities=None, fundamentals=None) -> List[dict]:
    """Universe for each rebalance date: [{'date', 'symbols'}]"""
    if fundamentals is not None and not fundamentals.empty and screen.fields:
        fundamentals = fundamentals[fundamentals['field'].isin(screen.fields)]
    history = []
    for date in dates:
        data = ScreenData.from_panels(date, closes, volumes, securities, fundamentals)
        selected = screen.select(data)
        history.append({'date': date, 'symbols': selected['symbol'].tolist()})
        logger.info("Screen %s on %s: %d symbols", screen.name, date.date(), len(selected))
    return history


class SignalPanel:
    """Indicator values for a set of symbols over a block of trading days (numpy, row = day)"""

    def __init__(self, indicators: Dict[str, pd.DataFrame], symbols, days: pd.DatetimeIndex):
        self.symbols = sorted(set(symbols) & set(indicators))
        self.col = {s: j for j, s in enumerate(self.symbols)}
        self.days = days
        self.values = {c: np.full((len(days), len(self.symbols)), np.nan) for c in SIGNAL_COLUMNS}
        for j, sym in enumerate(self.symbols):
            frame = indicators[sym].reindex(days)
            for c in SIGNAL_COLUMNS:
                self.values[c][:, j] = frame[c].to_numpy(dtype=float)

    def get(self, column: str, row: int, symbol: str) -> float:
        j = self.col.get(symbol)
        return np.nan if j is None else self.values[column][row, j]

    def signal(self, row: int, symbol: str) -> Optional[SymbolSignal]:
        j = self.col.get(symbol)
        if j is None:
            return None
        v = {c: self.values[c][row, j] for c in SIGNAL_COLUMNS}
        if np.isnan(v['vpvma']) or np.isnan(v['vpvmas']):
            return None
        return SymbolSignal(symbol, v['close'], v['vpvma'], v['vpvmas'], v['vpvma_prev'],
                            v['vpvmas_prev'], bool(v['buy_signal'] == 1), v['strength'])

    def buy_candidates(self, row: int, allowed: set) -> List[str]:
        hits = np.nonzero(self.values['buy_signal'][row] == 1)[0]
        return [self.symbols[j] for j in hits if self.symbols[j] in allowed]


def simulate(
    frames: Dict[str, pd.DataFrame],
    spy_data: pd.DataFrame,
    start_date,
    end_date,
    initial_capital: float = 100000,
    universe_history: Optional[List[dict]] = None,
) -> dict:
    """
    Day-by-day simulation.

    Args:
        frames: symbol -> OHLCV for every symbol that can be traded
        spy_data: SPY OHLCV (calendar + regime)
        universe_history: [{'date', 'symbols'}] from run_screens(); None trades every symbol
    """
    start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
    spy_data = spy_data.sort_values('timestamp').reset_index(drop=True)
    regime = bear_regime_series(spy_data)
    all_days = pd.DatetimeIndex(spy_data['timestamp'])
    trading_days = all_days[(all_days >= start) & (all_days <= end)]
    if len(trading_days) == 0:
        raise ValueError(f"No SPY trading days between {start.date()} and {end.date()}")

    if universe_history is None:
        universe_history = [{'date': trading_days[0], 'symbols': sorted(frames)}]
    period_starts = {h['date']: h['symbols'] for h in universe_history}

    logger.info("Computing indicators for %d symbols...", len(frames))
    indicators = {s: compute_indicator_frame(f) for s, f in frames.items() if len(f) > 0}
    last_bar = {s: f.index.max() for s, f in indicators.items()}
    day_pos = {d: i for i, d in enumerate(all_days)}

    portfolio = ProtectedPortfolio(initial_capital=initial_capital)
    marks: Dict[str, float] = {}
    pending = None
    pending_strength: Dict[str, float] = {}
    swap_streaks: Dict[str, int] = {}
    universe: set = set()
    panel: Optional[SignalPanel] = None
    row = -1

    total_days = len(trading_days)
    step = max(1, total_days // 20)

    for i, date in enumerate(trading_days):
        if i % step == 0:
            logger.info("Progress: %d%% (%s)", int(i / total_days * 100), date.date())

        # New screening period: new universe and a fresh signal panel for its days
        if date in period_starts or panel is None:
            if date in period_starts:
                universe = set(period_starts[date])
            next_starts = [d for d in period_starts if d > date]
            block_end = min(next_starts) if next_starts else trading_days[-1] + pd.Timedelta(days=1)
            block_days = trading_days[(trading_days >= date) & (trading_days < block_end)]
            needed = universe | set(portfolio.positions)
            if pending is not None:
                needed |= set(pending.buys) | {r['buy_symbol'] for r in pending.replacements}
            panel = SignalPanel(indicators, needed, block_days)
            row = -1
        row += 1

        # 1. Fill yesterday's orders at today's open
        unfilled_sells = []
        if pending is not None:
            exits = pending.sells + [{'symbol': r['sell_symbol'], 'reason': 'Replacement', 'fast_exit': False}
                                     for r in pending.replacements]
            for order in exits:
                sym = order['symbol']
                px = panel.get('open', row, sym)
                if np.isnan(px):
                    unfilled_sells.append(order)  # no bar today - retry at the next bar
                    continue
                portfolio.sell(sym, px, date, order['reason'], order['fast_exit'])
            equity = portfolio.equity(marks)
            for sym in [r['buy_symbol'] for r in pending.replacements] + pending.buys:
                px = panel.get('open', row, sym)
                if np.isnan(px):
                    portfolio.missed_signals += 1
                    continue
                portfolio.buy(sym, px, date, equity, pending_strength.get(sym, 0.0))

        # 2. Mark held positions to market
        for sym in portfolio.positions:
            px = panel.get('close', row, sym)
            if not np.isnan(px):
                marks[sym] = float(px)

        # 3. Force-exit positions whose data has stopped
        for sym in list(portfolio.positions):
            lb = last_bar.get(sym)
            if lb is not None and lb < date and day_pos[date] - day_pos.get(lb, -10**9) > DELIST_GRACE_DAYS:
                logger.warning("%s: no data since %s - closing at last close %.2f",
                               sym, lb.date(), marks.get(sym, np.nan))
                portfolio.sell(sym, marks.get(sym, portfolio.positions[sym]['entry_price']), date, 'No Data')

        # 4. Regime
        bearish = bool(regime.asof(date)) if len(regime) else False
        portfolio.protection_active = bearish and config.ENABLE_BEAR_PROTECTION
        portfolio.total_days += 1
        portfolio.protection_days += int(portfolio.protection_active)

        # 5. Today's signals: every holding + today's buy candidates in the universe
        signals = {}
        watch = set(portfolio.positions) | set(panel.buy_candidates(row, universe)) | set(swap_streaks)
        for sym in watch:
            sig = panel.signal(row, sym)
            if sig is not None:
                signals[sym] = sig
        portfolio.total_buy_signals += sum(1 for s in signals.values() if s.buy_signal and s.symbol in universe)

        # 6. Decide tomorrow's orders
        pending = plan_day(portfolio.positions, signals, portfolio.protection_active, universe,
                           swap_streaks=swap_streaks)
        swap_streaks = pending.swap_streaks
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
    return {
        'history': df_history,
        'trades': df_trades,
        'portfolio': portfolio,
        'metrics': compute_metrics(df_history, df_trades, initial_capital),
        'universe_history': universe_history,
    }


def run_backtest_on_frames(
    frames: Dict[str, pd.DataFrame],
    spy_data: pd.DataFrame,
    start_date,
    end_date,
    initial_capital: float = 100000,
    screen: Optional[Screen] = None,
    securities: pd.DataFrame = None,
    fundamentals: pd.DataFrame = None,
) -> dict:
    """
    Backtest on in-memory OHLCV frames (no database access).

    Args:
        frames: symbol -> DataFrame[timestamp, open, high, low, close, volume]
                (include history before start_date for indicator warmup)
        spy_data: SPY OHLCV; defines the trading calendar and the regime
        screen: Universe screen re-run each SCREEN_FREQUENCY period; None trades every symbol
        securities / fundamentals: Inputs for the screen (optional)
    """
    universe_history = None
    if screen is not None:
        closes, volumes = close_volume_panels(frames)
        days = pd.DatetimeIndex(spy_data['timestamp'])
        days = days[(days >= pd.Timestamp(start_date)) & (days <= pd.Timestamp(end_date))]
        universe_history = run_screens(screen, rebalance_dates(days), closes, volumes, securities, fundamentals)
        traded = set().union(*(set(h['symbols']) for h in universe_history))
        frames = {s: f for s, f in frames.items() if s in traded}
    return simulate(frames, spy_data, start_date, end_date, initial_capital, universe_history)


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


def load_close_volume_panels(db, symbols, start, end, chunk: int = 250) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Close/volume panels for many symbols, loaded in chunks to limit memory"""
    closes, volumes = [], []
    for k in range(0, len(symbols), chunk):
        bars = db.get_bars(start, end, symbols=symbols[k:k + chunk])
        closes.append(bars.pivot(index='timestamp', columns='symbol', values='close'))
        volumes.append(bars.pivot(index='timestamp', columns='symbol', values='volume'))
        logger.info("Loaded close/volume for %d/%d symbols", min(k + chunk, len(symbols)), len(symbols))
    return pd.concat(closes, axis=1).sort_index(), pd.concat(volumes, axis=1).sort_index()


def load_frames(db, symbols, start_date, end_date) -> Dict[str, pd.DataFrame]:
    """Full OHLCV for each symbol, with indicator warmup history"""
    load_start = pd.Timestamp(start_date) - timedelta(days=config.INDICATOR_LOOKBACK_DAYS)
    frames = {}
    for i, sym in enumerate(sorted(symbols), 1):
        try:
            df = db.get_ohlcv_data(sym, start_date=load_start, end_date=pd.Timestamp(end_date))
        except Exception:
            logger.exception("%s: failed to load data - excluded from backtest", sym)
            continue
        if not df.empty:
            frames[sym] = df
        if i % 250 == 0:
            logger.info("Loaded OHLCV for %d/%d symbols", i, len(symbols))
    return frames


def run_backtest(
    db,
    start_date,
    end_date,
    initial_capital: float = 100000,
    screen: Optional[Screen] = None,
    symbols: Optional[List[str]] = None,
):
    """
    Run the VPVMA backtest against the database.

    Args:
        db: Database instance
        start_date, end_date: Evaluation period
        initial_capital: Starting cash
        screen: Universe screen (same one live trading uses); None trades every symbol
        symbols: Candidate symbols (default: every symbol in the database except SPY)
    """
    start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
    symbols = [s for s in (symbols or db.list_symbols()) if s != 'SPY']
    spy_data = db.get_ohlcv_data('SPY', start_date=start - timedelta(days=config.REGIME_LOOKBACK_DAYS), end_date=end)
    days = pd.DatetimeIndex(spy_data['timestamp'])
    days = days[(days >= start) & (days <= end)]

    universe_history = None
    if screen is not None:
        closes, volumes = load_close_volume_panels(
            db, symbols, start - timedelta(days=config.SCREEN_LOOKBACK_DAYS), end)
        fundamentals = (db.get_fundamentals(end) if screen.fields else None)
        universe_history = run_screens(screen, rebalance_dates(days), closes, volumes,
                                       db.get_securities(), fundamentals)
        del closes, volumes
        symbols = sorted(set().union(*(set(h['symbols']) for h in universe_history)))

    frames = load_frames(db, symbols, start, end)
    logger.info("Simulating %d symbols, %s to %s", len(frames), start.date(), end.date())
    results = simulate(frames, spy_data, start, end, initial_capital, universe_history)
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
        f"Universe rebalances: {len(results['universe_history'])}",
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
    parser.add_argument('--screen', help=f'Screen name (default config.SCREEN_NAME = {config.SCREEN_NAME!r})')
    parser.add_argument('--no-screen', action='store_true', help='Trade every symbol in the database')
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
        start_date=args.start,
        end_date=end,
        initial_capital=args.capital,
        screen=None if args.no_screen else get_screen(args.screen),
    )
    if args.trades_csv:
        results['trades'].to_csv(args.trades_csv, index=False)
        logger.info("Trades written to %s", args.trades_csv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
