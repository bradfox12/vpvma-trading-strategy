"""
Trading signal generation logic
Implements Table 8 buy/sell rules with asymmetric bandwidth
"""

import numpy as np
from config import BANDWIDTH


def generate_buy_signals(vpvma: np.ndarray, vpvmas: np.ndarray) -> np.ndarray:
    """
    Generate buy signals based on Table 8 rules
    
    Buy Signal when BOTH conditions are true:
    1. VPVMA[t] > (1 + BANDWIDTH) × VPVMAS[t]  # Threshold: 1.1x
    2. VPVMA[t-1] <= VPVMAS[t-1]                # Ensures crossover
    
    The second condition prevents repeated signals when VPVMA stays above threshold.
    
    Args:
        vpvma: VPVMA line values
        vpvmas: VPVMAS signal line values
    
    Returns:
        np.ndarray: Boolean array (True = buy signal)
    
    References:
        Paper Table 8 - Buy Rules
    """
    # Calculate buy threshold: 1.1 × VPVMAS
    buy_threshold = (1 + BANDWIDTH) * vpvmas
    
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


def generate_sell_signals(vpvma: np.ndarray, vpvmas: np.ndarray) -> np.ndarray:
    """
    Generate sell signals based on Table 8 rules
    
    Sell Signal when BOTH conditions are true:
    1. VPVMA[t] < (1 - BANDWIDTH × 2) × VPVMAS[t]  # Threshold: 0.8x (asymmetric!)
    2. VPVMA[t-1] >= VPVMAS[t-1]                    # Ensures crossover
    
    Note: Bandwidth is multiplied by 2 for sell threshold (0.8x vs 1.1x for buy).
    This asymmetry is intentional per the paper.
    
    Args:
        vpvma: VPVMA line values
        vpvmas: VPVMAS signal line values
    
    Returns:
        np.ndarray: Boolean array (True = sell signal)
    
    References:
        Paper Table 8 - Sell Rules
    """
    # Calculate sell threshold: 0.8 × VPVMAS (asymmetric!)
    sell_threshold = (1 - BANDWIDTH * 2) * vpvmas
    
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