"""
Volume-weighted moving average calculations
Implements formulas 4.2-2 (SVWMA) and 4.2-3 (LVWMA)
"""

import numpy as np
import pandas as pd
import config


def calculate_vwma(typical_price: np.ndarray, volume: np.ndarray, window: int) -> np.ndarray:
    """
    Calculate Volume Weighted Moving Average (VWMA)
    
    VWMA = Σ(TP × V) / Σ(V) over window period
    
    This uses a fixed rolling window where each position has equal time-weight,
    but prices are volume-weighted within that window.
    
    Args:
        typical_price: Array of typical prices
        volume: Array of trading volumes
        window: Rolling window size
    
    Returns:
        np.ndarray: Volume-weighted moving average
    
    References:
        Paper Formulas 4.2-2 and 4.2-3
    """
    # Convert to pandas Series for rolling operations
    tp_series = pd.Series(typical_price)
    vol_series = pd.Series(volume)
    
    # Calculate numerator: rolling sum of (TP × Volume)
    tp_vol_product = tp_series * vol_series
    numerator = tp_vol_product.rolling(window=window, min_periods=window).sum()
    
    # Calculate denominator: rolling sum of Volume
    denominator = vol_series.rolling(window=window, min_periods=window).sum()
    
    # VWMA = numerator / denominator
    # Handle division by zero (return NaN if volume sum is 0)
    vwma = numerator / denominator
    
    return vwma.to_numpy()


def calculate_svwma(typical_price: np.ndarray, volume: np.ndarray) -> np.ndarray:
    """
    Calculate Short-term Volume Weighted Moving Average (SVWMA) - Formula 4.2-2
    
    Uses WINDOW_FAST (12) as the rolling window period.
    
    Args:
        typical_price: Array of typical prices
        volume: Array of trading volumes
    
    Returns:
        np.ndarray: Short-term VWMA
    
    References:
        Paper Formula 4.2-2
    """
    return calculate_vwma(typical_price, volume, config.WINDOW_FAST)


def calculate_lvwma(typical_price: np.ndarray, volume: np.ndarray) -> np.ndarray:
    """
    Calculate Long-term Volume Weighted Moving Average (LVWMA) - Formula 4.2-3
    
    Uses WINDOW_SLOW (26) as the rolling window period.
    
    Args:
        typical_price: Array of typical prices
        volume: Array of trading volumes
    
    Returns:
        np.ndarray: Long-term VWMA
    
    References:
        Paper Formula 4.2-3
    """
    return calculate_vwma(typical_price, volume, config.WINDOW_SLOW)