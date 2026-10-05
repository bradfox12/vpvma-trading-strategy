"""
Trading signal generation logic
Implements Table 8 buy/sell rules with INDEPENDENT buy/sell bandwidth

CRITICAL CHANGE FROM PAPER:
- Paper uses coupled bandwidth (sell = buy × 2)
- This implementation uses INDEPENDENT thresholds for better risk control
- Buy bandwidth: Controls entry selectivity (higher = more selective)
- Sell bandwidth: Controls exit timing (lower = tighter stops)

SIGN-SAFE BANDS:
- Bands are offset by bandwidth × |VPVMAS| rather than scaled by (1 ± bandwidth).
- For VPVMAS > 0 this is identical to the original (1 + bw) × VPVMAS form.
- For VPVMAS < 0 the original form put the buy band BELOW the signal line and
  the sell band ABOVE it, inverting the strategy on roughly half of all days.

BEAR MARKET PROTECTION:
- Accepts dynamic sell_bandwidth parameter
- Normal markets: config.SELL_BANDWIDTH
- Bear markets: config.BEAR_SELL_BANDWIDTH

This module is the single source of truth for the entry/exit rules. The
backtest and the live portfolio manager both call buy_threshold(),
sell_threshold(), is_sell() and signal_strength() rather than re-implementing them.
"""

import numpy as np
import config


def buy_threshold(vpvmas, buy_bandwidth: float = None):
    """VPVMA level that must be exceeded for an entry: VPVMAS + bw × |VPVMAS|"""
    if buy_bandwidth is None:
        buy_bandwidth = config.BUY_BANDWIDTH
    return vpvmas + buy_bandwidth * np.abs(vpvmas)


def sell_threshold(vpvmas, sell_bandwidth: float = None):
    """VPVMA level that triggers an exit: VPVMAS - 2 × bw × |VPVMAS|

    The ×2 keeps the paper's asymmetric convention (sell_bandwidth=0.08 exits
    at 0.84 × VPVMAS when VPVMAS is positive).
    """
    if sell_bandwidth is None:
        sell_bandwidth = config.SELL_BANDWIDTH
    return vpvmas - 2 * sell_bandwidth * np.abs(vpvmas)


def signal_strength(vpvma, vpvmas, buy_bandwidth: float = None):
    """How far VPVMA is above the buy threshold, scaled by |VPVMAS| (higher = stronger)"""
    scale = np.abs(vpvmas)
    if np.ndim(scale) == 0:
        if scale == 0 or np.isnan(scale):
            return 0.0
        return float((vpvma - buy_threshold(vpvmas, buy_bandwidth)) / scale)
    with np.errstate(divide='ignore', invalid='ignore'):
        out = (vpvma - buy_threshold(vpvmas, buy_bandwidth)) / scale
    return np.where(scale > 0, out, 0.0)


def generate_buy_signals(
    vpvma: np.ndarray,
    vpvmas: np.ndarray,
    buy_bandwidth: float = None
) -> np.ndarray:
    """
    Generate buy signals with independent buy threshold

    Buy Signal when BOTH conditions are true:
    1. VPVMA[t] > VPVMAS[t] + buy_bandwidth × |VPVMAS[t]|   # Entry threshold
    2. VPVMA[t-1] <= VPVMAS[t-1]                           # Ensures crossover

    The second condition prevents repeated signals when VPVMA stays above threshold.
    NaN values (warmup period) never produce signals.

    Args:
        vpvma: VPVMA line values
        vpvmas: VPVMAS signal line values
        buy_bandwidth: Buy threshold (default: config.BUY_BANDWIDTH)

    Returns:
        np.ndarray: Boolean array (True = buy signal)

    References:
        Paper Table 8 - Buy Rules (modified for independent bandwidth)
    """
    vpvma = np.asarray(vpvma, dtype=float)
    vpvmas = np.asarray(vpvmas, dtype=float)

    above_threshold = vpvma > buy_threshold(vpvmas, buy_bandwidth)

    # Previous bar was at or below signal line (crossover detection)
    crossover = np.zeros_like(vpvma, dtype=bool)
    crossover[1:] = vpvma[:-1] <= vpvmas[:-1]

    return above_threshold & crossover


def generate_sell_signals(
    vpvma: np.ndarray,
    vpvmas: np.ndarray,
    sell_bandwidth: float = None
) -> np.ndarray:
    """
    Generate sell signals with independent sell threshold

    Sell Signal when BOTH conditions are true:
    1. VPVMA[t] < VPVMAS[t] - 2 × sell_bandwidth × |VPVMAS[t]|   # Exit threshold
    2. VPVMA[t-1] >= VPVMAS[t-1]                                 # Ensures crossover

    BEAR MARKET PROTECTION:
    - Pass config.BEAR_SELL_BANDWIDTH in bear markets for FastExit

    Args:
        vpvma: VPVMA line values
        vpvmas: VPVMAS signal line values
        sell_bandwidth: Exit threshold (default: config.SELL_BANDWIDTH)

    Returns:
        np.ndarray: Boolean array (True = sell signal)

    References:
        Paper Table 8 - Sell Rules (modified for independent bandwidth)
    """
    vpvma = np.asarray(vpvma, dtype=float)
    vpvmas = np.asarray(vpvmas, dtype=float)

    below_threshold = vpvma < sell_threshold(vpvmas, sell_bandwidth)

    crossover = np.zeros_like(vpvma, dtype=bool)
    crossover[1:] = vpvma[:-1] >= vpvmas[:-1]

    return below_threshold & crossover


def is_sell(vpvma_prev, vpvmas_prev, vpvma_now, vpvmas_now, sell_bandwidth: float = None) -> bool:
    """Scalar form of generate_sell_signals() for a single bar"""
    if any(v is None or np.isnan(v) for v in (vpvma_prev, vpvmas_prev, vpvma_now, vpvmas_now)):
        return False
    return bool(vpvma_prev >= vpvmas_prev and vpvma_now < sell_threshold(vpvmas_now, sell_bandwidth))


def combine_signals(buy_signals: np.ndarray, sell_signals: np.ndarray) -> np.ndarray:
    """
    Combine buy and sell signals into unified signal array

    Args:
        buy_signals: Boolean array of buy signals
        sell_signals: Boolean array of sell signals

    Returns:
        np.ndarray: Integer array where:
            1 = buy signal
            -1 = sell signal
            0 = hold (no signal)

    Raises:
        ValueError: If simultaneous buy and sell signals detected
    """
    if np.any(buy_signals & sell_signals):
        raise ValueError("Simultaneous buy and sell signals detected")

    signals = np.zeros(len(buy_signals), dtype=int)
    signals[buy_signals] = 1
    signals[sell_signals] = -1

    return signals


def get_sell_bandwidth(spy_bearish: bool) -> float:
    """Regime-dependent sell bandwidth (FastExit when SPY < 200MA)"""
    if spy_bearish and config.ENABLE_BEAR_PROTECTION:
        return config.BEAR_SELL_BANDWIDTH
    return config.SELL_BANDWIDTH
