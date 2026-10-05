"""
Exponential moving average calculations
Implements formulas 4.2-5 (ESVMap) and 4.2-6 (ElVMap)
"""

import numpy as np
import pandas as pd
import config


def calculate_ema(data: np.ndarray, period: int) -> np.ndarray:
    """
    Calculate Exponential Moving Average (EMA)
    
    α = 2 / (period + 1)
    EMA[t] = α × data[t] + (1 - α) × EMA[t-1]
    
    Uses pandas EMA implementation for efficiency and accuracy.
    
    Args:
        data: Input data array
        period: EMA period
    
    Returns:
        np.ndarray: Exponential moving average
    """
    series = pd.Series(data)
    ema = series.ewm(span=period, adjust=False).mean()
    return ema.to_numpy()


def calculate_esvmap(svwma: np.ndarray, daily_volatility: np.ndarray) -> np.ndarray:
    """
    Calculate EMA of Short-term Volume-Price Product (ESVMap) - Formula 4.2-5
    
    ESVMap = EMA(SVWMA × DV, config.WINDOW_FAST)
    
    Args:
        svwma: Short-term volume-weighted moving average
        daily_volatility: Daily volatility array
    
    Returns:
        np.ndarray: ESVMap values
    
    References:
        Paper Formula 4.2-5
    """
    # Element-wise multiplication
    svwma_dv_product = svwma * daily_volatility
    
    # Apply EMA with short-term period
    esvmap = calculate_ema(svwma_dv_product, config.WINDOW_FAST)
    
    return esvmap


def calculate_elvmap(lvwma: np.ndarray, daily_volatility: np.ndarray) -> np.ndarray:
    """
    Calculate EMA of Long-term Volume-Price Product (ElVMap) - Formula 4.2-6
    
    ElVMap = EMA(LVWMA × DV, config.WINDOW_SLOW)
    
    Args:
        lvwma: Long-term volume-weighted moving average
        daily_volatility: Daily volatility array
    
    Returns:
        np.ndarray: ElVMap values
    
    References:
        Paper Formula 4.2-6
    """
    # Element-wise multiplication
    lvwma_dv_product = lvwma * daily_volatility
    
    # Apply EMA with long-term period
    elvmap = calculate_ema(lvwma_dv_product, config.WINDOW_SLOW)
    
    return elvmap