"""
Price metrics calculations for VPVMA indicator
Implements formulas 4.2-1 (Typical Price) and 4.2-4 (Daily Volatility)
"""

import numpy as np


def calculate_typical_price(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    """
    Calculate Typical Price (TP) - Formula 4.2-1
    
    TP = (High + Low + Close) / 3
    
    Args:
        high: Array of high prices
        low: Array of low prices
        close: Array of closing prices
    
    Returns:
        np.ndarray: Typical price for each period
    
    References:
        Paper Formula 4.2-1
    """
    return (high + low + close) / 3.0


def calculate_daily_volatility(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    open_price: np.ndarray
) -> np.ndarray:
    """
    Calculate Daily Volatility (DV) - Formula 4.2-4
    
    DV = Std(High, Low, Close, Open)
    
    CRITICAL: This is per-period standard deviation (std of 4 values at each time t),
    NOT a rolling window standard deviation.
    
    Args:
        high: Array of high prices
        low: Array of low prices
        close: Array of closing prices
        open_price: Array of opening prices
    
    Returns:
        np.ndarray: Daily volatility for each period
    
    References:
        Paper Formula 4.2-4
    """
    # Stack OHLC into a 2D array: shape (4, n_periods)
    ohlc = np.stack([open_price, high, low, close], axis=0)
    
    # Calculate standard deviation along axis 0 (across the 4 prices at each time period)
    # ddof=1 for sample standard deviation
    daily_vol = np.std(ohlc, axis=0, ddof=1)
    
    return daily_vol