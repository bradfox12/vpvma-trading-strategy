"""
Core VPVMA calculations
Implements formulas 4.2-7 (VPVMA) and 4.2-8 (VPVMAS)
"""

import numpy as np
import pandas as pd
from config import WINDOW_SIGN


def calculate_vpvma(esvmap: np.ndarray, elvmap: np.ndarray) -> np.ndarray:
    """
    Calculate VPVMA Line - Formula 4.2-7
    
    VPVMA = ESVMap - ElVMap
    
    This is the main indicator line.
    
    Args:
        esvmap: Short-term EMA of volume-price product
        elvmap: Long-term EMA of volume-price product
    
    Returns:
        np.ndarray: VPVMA values
    
    References:
        Paper Formula 4.2-7
    """
    return esvmap - elvmap


def calculate_vpvmas(vpvma: np.ndarray) -> np.ndarray:
    """
    Calculate VPVMA Signal Line (VPVMAS) - Formula 4.2-8
    
    VPVMAS = Σ(VPVMA) / WINDOW_SIGN
    
    CRITICAL: This is a Simple Moving Average (SMA), NOT an Exponential Moving Average (EMA).
    The paper uses summation and division, which is SMA.
    
    Args:
        vpvma: VPVMA line values
    
    Returns:
        np.ndarray: VPVMAS signal line values
    
    References:
        Paper Formula 4.2-8
    """
    # Convert to pandas Series for rolling SMA
    vpvma_series = pd.Series(vpvma)
    
    # Calculate Simple Moving Average (NOT EMA)
    vpvmas = vpvma_series.rolling(window=WINDOW_SIGN, min_periods=WINDOW_SIGN).mean()
    
    return vpvmas.to_numpy()