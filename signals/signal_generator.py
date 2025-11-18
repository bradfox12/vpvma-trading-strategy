"""
Trading signal generation logic
Implements Table 8 buy/sell rules with INDEPENDENT buy/sell bandwidth

CRITICAL CHANGE FROM PAPER:
- Paper uses coupled bandwidth (sell = buy × 2)
- This implementation uses INDEPENDENT thresholds for better risk control
- Buy bandwidth: Controls entry selectivity (higher = more selective)
- Sell bandwidth: Controls exit timing (lower = tighter stops)

BEAR MARKET PROTECTION (NEW):
- Accepts dynamic sell_bandwidth parameter
- Normal markets: sell_bandwidth from config.SELL_BANDWIDTH (0.08)
- Bear markets: sell_bandwidth from config.BEAR_SELL_BANDWIDTH (0.04)
- This enables FastExit+SPY200 protection mechanism
"""

import numpy as np
from config import BUY_BANDWIDTH, SELL_BANDWIDTH


def generate_buy_signals(
    vpvma: np.ndarray,
    vpvmas: np.ndarray,
    buy_bandwidth: float = None
) -> np.ndarray:
    """
    Generate buy signals with independent buy threshold
    
    Buy Signal when BOTH conditions are true:
    1. VPVMA[t] > (1 + buy_bandwidth) × VPVMAS[t]  # Entry threshold
    2. VPVMA[t-1] <= VPVMAS[t-1]                   # Ensures crossover
    
    The second condition prevents repeated signals when VPVMA stays above threshold.
    
    Args:
        vpvma: VPVMA line values
        vpvmas: VPVMAS signal line values
        buy_bandwidth: Buy threshold (default: from config.BUY_BANDWIDTH)
    
    Returns:
        np.ndarray: Boolean array (True = buy signal)
    
    Example:
        >>> # Normal usage (uses config default)
        >>> buy_signals = generate_buy_signals(vpvma, vpvmas)
        >>> 
        >>> # Custom bandwidth
        >>> buy_signals = generate_buy_signals(vpvma, vpvmas, buy_bandwidth=0.20)
        >>> 
        >>> # BUY_BANDWIDTH = 0.18 → Buy when VPVMA > 1.18 × VPVMAS
    
    References:
        Paper Table 8 - Buy Rules (modified for independent bandwidth)
    """
    # Use default from config if not specified
    if buy_bandwidth is None:
        buy_bandwidth = BUY_BANDWIDTH
    
    # Calculate buy threshold using buy_bandwidth
    buy_threshold = (1 + buy_bandwidth) * vpvmas
    
    # Condition 1: VPVMA is above threshold
    above_threshold = vpvma > buy_threshold
    
    # Condition 2: Previous bar was at or below signal line (crossover detection)
    # Shift arrays to compare current with previous
    vpvma_prev = np.roll(vpvma, 1)
    vpvmas_prev = np.roll(vpvmas, 1)
    
    # Set first element to False (no previous bar)
    crossover = np.zeros_like(vpvma, dtype=bool)
    crossover[1:] = vpvma_prev[1:] <= vpvmas_prev[1:]
    
    # Both conditions must be true
    buy_signals = above_threshold & crossover
    
    return buy_signals


def generate_sell_signals(
    vpvma: np.ndarray,
    vpvmas: np.ndarray,
    sell_bandwidth: float = None
) -> np.ndarray:
    """
    Generate sell signals with independent sell threshold
    
    Sell Signal when BOTH conditions are true:
    1. VPVMA[t] < (1 - sell_bandwidth × 2) × VPVMAS[t]  # Exit threshold
    2. VPVMA[t-1] >= VPVMAS[t-1]                        # Ensures crossover
    
    CRITICAL: This uses sell_bandwidth × 2 to maintain paper's asymmetric convention
    This allows independent control of exit timing vs entry selectivity.
    
    BEAR MARKET PROTECTION:
    - Pass lower sell_bandwidth in bear markets for FastExit
    - Normal: sell_bandwidth=0.08 (exit at 0.84× VPVMAS)
    - Bear: sell_bandwidth=0.04 (exit at 0.92× VPVMAS = 2x faster)
    
    Args:
        vpvma: VPVMA line values
        vpvmas: VPVMAS signal line values
        sell_bandwidth: Exit threshold (default: from config.SELL_BANDWIDTH)
    
    Returns:
        np.ndarray: Boolean array (True = sell signal)
    
    Example:
        >>> # Normal usage (uses config default = 0.08)
        >>> sell_signals = generate_sell_signals(vpvma, vpvmas)
        >>> 
        >>> # FastExit in bear market (tighter threshold)
        >>> sell_signals = generate_sell_signals(vpvma, vpvmas, sell_bandwidth=0.04)
        >>> 
        >>> # With protection system
        >>> from protection import detect_bear_regime, get_adaptive_sell_bandwidth
        >>> spy_bearish = detect_bear_regime(db, current_date)
        >>> sell_bw = get_adaptive_sell_bandwidth(spy_bearish)
        >>> sell_signals = generate_sell_signals(vpvma, vpvmas, sell_bandwidth=sell_bw)
        
    Note:
        Lower sell_bandwidth = Tighter stops (cut losers faster)
        Higher sell_bandwidth = Looser stops (give trades more room)
    
    References:
        Paper Table 8 - Sell Rules (modified for independent bandwidth)
    """
    # Use default from config if not specified
    if sell_bandwidth is None:
        sell_bandwidth = SELL_BANDWIDTH
    
    # Calculate sell threshold using sell_bandwidth
    # NOTE: ×2 multiplier creates asymmetric band (sell = buy_bandwidth × 2)
    # This matches original paper convention and phase3 validation
    # Example: sell_bandwidth=0.08 → threshold=0.84× VPVMAS
    sell_threshold = (1 - sell_bandwidth * 2) * vpvmas
    
    # Condition 1: VPVMA is below threshold
    below_threshold = vpvma < sell_threshold
    
    # Condition 2: Previous bar was at or above signal line (crossover detection)
    vpvma_prev = np.roll(vpvma, 1)
    vpvmas_prev = np.roll(vpvmas, 1)
    
    # Set first element to False (no previous bar)
    crossover = np.zeros_like(vpvma, dtype=bool)
    crossover[1:] = vpvma_prev[1:] >= vpvmas_prev[1:]
    
    # Both conditions must be true
    sell_signals = below_threshold & crossover
    
    return sell_signals


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
        AssertionError: If simultaneous buy and sell signals detected
    """
    # Validate no simultaneous signals (should never happen with proper logic)
    simultaneous = buy_signals & sell_signals
    assert not np.any(simultaneous), "Simultaneous buy and sell signals detected"
    
    # Create signal array
    signals = np.zeros(len(buy_signals), dtype=int)
    signals[buy_signals] = 1
    signals[sell_signals] = -1
    
    return signals


# ============================================================================
# PROTECTION-AWARE SIGNAL GENERATION (CONVENIENCE FUNCTION)
# ============================================================================

def generate_signals_with_protection(
    vpvma: np.ndarray,
    vpvmas: np.ndarray,
    spy_bearish: bool = False,
    buy_bandwidth: float = None,
    bull_sell_bandwidth: float = None,
    bear_sell_bandwidth: float = None
) -> dict:
    """
    Generate buy/sell signals with automatic bear market protection
    
    This is a convenience wrapper that:
    1. Detects if bear protection should activate
    2. Selects appropriate sell bandwidth
    3. Generates buy and sell signals
    4. Returns combined signals plus metadata
    
    Args:
        vpvma: VPVMA line values
        vpvmas: VPVMAS signal line values
        spy_bearish: True if SPY < 200MA (bear market)
        buy_bandwidth: Buy threshold (default: config.BUY_BANDWIDTH)
        bull_sell_bandwidth: Normal sell threshold (default: config.SELL_BANDWIDTH)
        bear_sell_bandwidth: FastExit threshold (default: config.BEAR_SELL_BANDWIDTH)
    
    Returns:
        dict: {
            'buy_signals': np.ndarray (boolean),
            'sell_signals': np.ndarray (boolean),
            'combined': np.ndarray (1=buy, -1=sell, 0=hold),
            'sell_bandwidth_used': float,
            'protection_active': bool
        }
    
    Example:
        >>> from protection import detect_bear_regime
        >>> 
        >>> # Detect regime
        >>> spy_bearish = detect_bear_regime(db, current_date)
        >>> 
        >>> # Generate signals with protection
        >>> result = generate_signals_with_protection(vpvma, vpvmas, spy_bearish)
        >>> 
        >>> # Use signals
        >>> buy_signals = result['buy_signals']
        >>> sell_signals = result['sell_signals']
        >>> 
        >>> # Check if protection was active
        >>> if result['protection_active']:
        >>>     print(f"⚠️ FastExit active (sell_bw={result['sell_bandwidth_used']})")
    """
    from config import BUY_BANDWIDTH, SELL_BANDWIDTH, BEAR_SELL_BANDWIDTH
    
    # Use defaults from config if not specified
    if buy_bandwidth is None:
        buy_bandwidth = BUY_BANDWIDTH
    if bull_sell_bandwidth is None:
        bull_sell_bandwidth = SELL_BANDWIDTH
    if bear_sell_bandwidth is None:
        bear_sell_bandwidth = BEAR_SELL_BANDWIDTH
    
    # Select appropriate sell bandwidth
    sell_bw = bear_sell_bandwidth if spy_bearish else bull_sell_bandwidth
    
    # Generate signals
    buy_signals = generate_buy_signals(vpvma, vpvmas, buy_bandwidth=buy_bandwidth)
    sell_signals = generate_sell_signals(vpvma, vpvmas, sell_bandwidth=sell_bw)
    combined = combine_signals(buy_signals, sell_signals)
    
    return {
        'buy_signals': buy_signals,
        'sell_signals': sell_signals,
        'combined': combined,
        'sell_bandwidth_used': sell_bw,
        'protection_active': spy_bearish
    }