"""
VPVMA strategy decision engine - shared by backtest.py and daily_portfolio_manager.py

Everything that decides WHAT to trade lives here as pure functions with no
database, file or clock access, so the backtest and live trading cannot drift
apart:

- symbol_signal(): latest VPVMA values + buy flag + strength for one symbol
- plan_day(): sells (signal / universe drop), buffered swaps and new buys
- shares_for(): position sizing

Which symbols are tradable is decided by screens.py.

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
    replacements: List[dict] = field(default_factory=list)   # {'sell_symbol', 'buy_symbol', 'sell_rank', 'buy_rank', 'confirm_days'}
    buys: List[str] = field(default_factory=list)
    missed_signals: int = 0
    swap_streaks: Dict[str, int] = field(default_factory=dict)  # candidate -> consecutive closes ranked within MAX_POSITIONS


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


def plan_day(
    held: Dict[str, dict],
    signals: Dict[str, SymbolSignal],
    spy_bearish: bool,
    universe: Optional[Iterable[str]] = None,
    swap_streaks: Optional[Dict[str, int]] = None,
    max_positions: int = None,
) -> DayPlan:
    """
    Decide the day's orders from the close's signals.

    1. Exits: sell signal (FastExit bandwidth in bear regime) or no longer in the universe
    2. Buy candidates: today's buy signals in the universe, strongest first
    3. Free slots are filled with the strongest candidates
    4. Rank buffer: holdings and waiting candidates (buy signals that did not
       get a slot) are ranked together by strength each close. A candidate that
       ranks within MAX_POSITIONS (and stays above its own buy threshold) on
       SWAP_CONFIRM_DAYS consecutive closes replaces the weakest holding ranked
       worse than SWAP_EXIT_RANK. MAX_SWAPS_PER_DAY caps swaps (None = no cap).

    Args:
        held: symbol -> position dict
        signals: symbol -> SymbolSignal for symbols with a bar today (at least
                 every held symbol, today's buy signals and every symbol in swap_streaks)
        spy_bearish: Regime at today's close
        universe: Tradable symbols; None = every symbol in `signals`
        swap_streaks: plan.swap_streaks from the previous session (carry it forward)
        max_positions: Position cap (default config.MAX_POSITIONS)
    """
    if max_positions is None:
        max_positions = config.MAX_POSITIONS

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

    # 3. Fill free slots
    free_slots = max(0, max_positions - len(remaining))
    plan.buys = [c.symbol for c in candidates[:free_slots]]
    leftover = candidates[free_slots:]

    # 4. Rank buffer: rank every current signal (holdings + waiting candidates)
    #    by strength. A candidate must rank within MAX_POSITIONS on
    #    SWAP_CONFIRM_DAYS consecutive closes; it then replaces the weakest
    #    holding ranked worse than SWAP_EXIT_RANK.
    prior = swap_streaks or {}
    pool = {c.symbol: c for c in leftover}                             # today's unfilled buy signals
    for sym in prior:                                                  # candidates already counting
        sig = signals.get(sym)
        if sig is not None and sym not in held and sym not in plan.buys \
                and (universe_set is None or sym in universe_set):
            pool.setdefault(sym, sig)

    holdings = {sym: signals[sym] for sym in remaining if sym in signals}
    ranked = sorted(list(holdings.values()) + list(pool.values()), key=lambda s: (-s.strength, s.symbol))
    rank = {sig.symbol: i for i, sig in enumerate(ranked, 1)}

    streaks = {}
    if len(remaining) + len(plan.buys) >= max_positions:
        for sym, sig in pool.items():
            # still a valid signal (above its buy threshold) and ranked inside the book
            if sig.strength > 0 and rank[sym] <= max_positions:
                streaks[sym] = prior.get(sym, 0) + 1

    swappable = sorted((sig for sym, sig in holdings.items() if rank[sym] > config.SWAP_EXIT_RANK),
                       key=lambda s: (s.strength, s.symbol))           # weakest first
    confirmed = sorted((pool[sym] for sym, n in streaks.items() if n >= config.SWAP_CONFIRM_DAYS),
                       key=lambda s: (-s.strength, s.symbol))
    for weak, cand in zip(swappable, confirmed):
        if config.MAX_SWAPS_PER_DAY and len(plan.replacements) >= config.MAX_SWAPS_PER_DAY:
            break
        plan.replacements.append({'sell_symbol': weak.symbol, 'buy_symbol': cand.symbol,
                                  'sell_rank': rank[weak.symbol], 'buy_rank': rank[cand.symbol],
                                  'confirm_days': streaks[cand.symbol]})
        del streaks[cand.symbol]

    plan.swap_streaks = streaks
    plan.missed_signals = sum(1 for c in leftover if c.symbol not in streaks
                              and c.symbol not in {r['buy_symbol'] for r in plan.replacements})
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
