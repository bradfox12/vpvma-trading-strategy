"""
VPVMA strategy decision engine - shared by backtest.py and daily_portfolio_manager.py

Everything that decides WHAT to trade lives here as pure functions with no
database, file or clock access, so the backtest and live trading cannot drift
apart:

- symbol_signal(): latest VPVMA values + buy flag + strength for one symbol
- rank_by_momentum(): monthly momentum universe selection
- plan_day(): sells (signal / universe drop), loser replacements and new buys
- shares_for(): position sizing

HOW and WHEN orders are filled (next open in the backtest, broker orders live)
stays in the callers.
"""

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

import config
from main import calculate_vpvma_indicator
from signals.signal_generator import get_sell_bandwidth, is_sell, signal_strength

# A held loser is swapped for a buy candidate whose strength is at least this
# much better: (candidate - current) / |current| >= REPLACEMENT_MIN_IMPROVEMENT
REPLACEMENT_MIN_IMPROVEMENT = 0.25


@dataclass
class SymbolSignal:
    """Indicator state for one symbol at the close of one bar"""
    symbol: str
    price: float
    vpvma: float
    vpvmas: float
    vpvma_prev: float
    vpvmas_prev: float
    buy_signal: bool
    strength: float


@dataclass
class DayPlan:
    """Orders decided at one close, to be executed at the next open"""
    sells: List[dict] = field(default_factory=list)          # {'symbol', 'reason', 'fast_exit'}
    replacements: List[dict] = field(default_factory=list)   # {'sell_symbol', 'buy_symbol', 'improvement'}
    buys: List[str] = field(default_factory=list)
    missed_signals: int = 0


def compute_indicator_frame(df: pd.DataFrame) -> pd.DataFrame:
    """
    VPVMA columns for a full OHLCV history (one symbol), indexed by timestamp.

    Columns: open, close, vpvma, vpvmas, vpvma_prev, vpvmas_prev, buy_signal, strength
    """
    result = calculate_vpvma_indicator(
        high=df['high'].to_numpy(dtype=float),
        low=df['low'].to_numpy(dtype=float),
        close=df['close'].to_numpy(dtype=float),
        open_price=df['open'].to_numpy(dtype=float),
        volume=df['volume'].to_numpy(dtype=float),
    )
    frame = pd.DataFrame({
        'open': df['open'].to_numpy(dtype=float),
        'close': df['close'].to_numpy(dtype=float),
        'vpvma': result['vpvma'],
        'vpvmas': result['vpvmas'],
        'buy_signal': result['buy_signals'],
    }, index=pd.DatetimeIndex(df['timestamp']))
    frame['vpvma_prev'] = frame['vpvma'].shift(1)
    frame['vpvmas_prev'] = frame['vpvmas'].shift(1)
    frame['strength'] = signal_strength(frame['vpvma'].to_numpy(), frame['vpvmas'].to_numpy())
    return frame


def signal_from_row(symbol: str, row) -> Optional[SymbolSignal]:
    """SymbolSignal from one row of compute_indicator_frame(); None during warmup"""
    if np.isnan(row['vpvma']) or np.isnan(row['vpvmas']):
        return None
    return SymbolSignal(
        symbol=symbol,
        price=float(row['close']),
        vpvma=float(row['vpvma']),
        vpvmas=float(row['vpvmas']),
        vpvma_prev=float(row['vpvma_prev']),
        vpvmas_prev=float(row['vpvmas_prev']),
        buy_signal=bool(row['buy_signal']),
        strength=float(row['strength']),
    )


def symbol_signal(symbol: str, df: pd.DataFrame) -> Optional[SymbolSignal]:
    """Signal at the last bar of an OHLCV history; None if not enough data"""
    if df is None or len(df) < config.WINDOW_SLOW + config.WINDOW_SIGN + 1:
        return None
    frame = compute_indicator_frame(df)
    return signal_from_row(symbol, frame.iloc[-1])


def rank_by_momentum(
    closes: Dict[str, pd.Series],
    asof: pd.Timestamp,
    period: int,
    size: int,
) -> pd.DataFrame:
    """
    Top `size` symbols by `period`-bar price momentum using data up to `asof`.

    Args:
        closes: symbol -> close prices indexed by timestamp
        asof: Last bar that may be used (no look-ahead)
        period: Momentum lookback in bars
        size: Number of symbols to return

    Returns:
        DataFrame [symbol, momentum_score, current_price, past_price] sorted descending
    """
    rows = []
    for symbol, series in closes.items():
        recent = series.loc[:asof].dropna().tail(period + 1)
        if len(recent) < period + 1:
            continue
        past, current = float(recent.iloc[0]), float(recent.iloc[-1])
        if past <= 0:
            continue
        rows.append({
            'symbol': symbol,
            'momentum_score': current / past - 1,
            'current_price': current,
            'past_price': past,
        })
    ranked = pd.DataFrame(rows, columns=['symbol', 'momentum_score', 'current_price', 'past_price'])
    if ranked.empty:
        return ranked
    return ranked.sort_values('momentum_score', ascending=False).head(size).reset_index(drop=True)


def plan_day(
    held: Dict[str, dict],
    signals: Dict[str, SymbolSignal],
    spy_bearish: bool,
    universe: Optional[Iterable[str]] = None,
    max_positions: int = None,
    enable_replacement: bool = None,
) -> DayPlan:
    """
    Decide the day's orders from the close's signals.

    Args:
        held: symbol -> position dict with at least 'entry_price'
        signals: symbol -> SymbolSignal for every symbol with valid data today
        spy_bearish: Regime at today's close (FastExit when True)
        universe: Tradable symbols; None = every symbol in `signals`.
                  Held symbols outside the universe are sold ('Universe Drop').
        max_positions: Position cap (default config.MAX_POSITIONS)
        enable_replacement: Swap losers for much stronger signals
                            (default config.ENABLE_REPLACEMENT)
    """
    if max_positions is None:
        max_positions = config.MAX_POSITIONS
    if enable_replacement is None:
        enable_replacement = config.ENABLE_REPLACEMENT

    plan = DayPlan()
    universe_set = set(universe) if universe is not None else None
    sell_bw = get_sell_bandwidth(spy_bearish)

    # 1. Exits
    for symbol in sorted(held):
        if universe_set is not None and symbol not in universe_set:
            plan.sells.append({'symbol': symbol, 'reason': 'Universe Drop', 'fast_exit': False})
            continue
        sig = signals.get(symbol)
        if sig is not None and is_sell(sig.vpvma_prev, sig.vpvmas_prev, sig.vpvma, sig.vpvmas, sell_bw):
            plan.sells.append({'symbol': symbol, 'reason': 'Signal', 'fast_exit': bool(spy_bearish)})

    sold = {s['symbol'] for s in plan.sells}
    remaining = [s for s in held if s not in sold]

    # 2. Ranked buy candidates
    candidates = sorted(
        (sig for sym, sig in signals.items()
         if sig.buy_signal and sym not in held
         and (universe_set is None or sym in universe_set)),
        key=lambda s: (-s.strength, s.symbol),
    )
    used = set()

    # 3. Replace losers when the book is still full after exits
    if enable_replacement and len(remaining) >= max_positions:
        for symbol in sorted(remaining):
            sig = signals.get(symbol)
            if sig is None or sig.price >= held[symbol]['entry_price']:
                continue
            for cand in candidates:
                if cand.symbol in used:
                    continue
                if sig.strength != 0:
                    improvement = (cand.strength - sig.strength) / abs(sig.strength)
                else:
                    improvement = float('inf')
                if improvement >= REPLACEMENT_MIN_IMPROVEMENT:
                    plan.replacements.append({
                        'sell_symbol': symbol,
                        'buy_symbol': cand.symbol,
                        'improvement': improvement,
                    })
                    used.add(cand.symbol)
                    break

    # 4. Fill free slots with the strongest unused candidates
    free_slots = max(0, max_positions - len(remaining))
    unused = [c for c in candidates if c.symbol not in used]
    plan.buys = [c.symbol for c in unused[:free_slots]]
    plan.missed_signals = max(0, len(unused) - free_slots)
    return plan


def shares_for(equity: float, price: float, cash: float) -> int:
    """
    Whole shares for one new position: POSITION_SIZE_PCT of equity,
    net of commission, never more than available cash.
    """
    if price <= 0 or np.isnan(price):
        return 0
    budget = min(equity * config.POSITION_SIZE_PCT, cash) - config.COMMISSION
    return max(0, int(budget / price))


def fill_price(price: float, side: str) -> float:
    """Price after slippage (buys pay up, sells receive less)"""
    slip = price * config.SLIPPAGE_BPS / 10000
    return price + slip if side == 'BUY' else price - slip
