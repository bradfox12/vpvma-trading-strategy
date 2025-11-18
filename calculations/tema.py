"""
Triple Exponential Moving Average (TEMA) calculations
Supports both standard TEMA (one period) and advanced TEMA (three periods)

Standard TEMA: All three EMAs use the same period
Advanced TEMA: Each EMA uses a different period for optimization
"""

import numpy as np
import pandas as pd


def calculate_ema(data: np.ndarray, period: int) -> np.ndarray:
    """
    Calculate Exponential Moving Average (EMA)
    
    α = 2 / (period + 1)
    EMA[t] = α × data[t] + (1 - α) × EMA[t-1]
    
    Args:
        data: Input data array
        period: EMA period
    
    Returns:
        np.ndarray: Exponential moving average
    """
    series = pd.Series(data)
    ema = series.ewm(span=period, adjust=False).mean()
    return ema.to_numpy()


def calculate_tema(
    data: np.ndarray,
    period: int = 21,
    period2: int = None,
    period3: int = None
) -> np.ndarray:
    """
    Calculate Triple Exponential Moving Average (TEMA)
    
    STANDARD TEMA (one period):
        TEMA = 3×EMA₁ - 3×EMA₂ + EMA₃
        where EMA₁ = EMA(price, period)
              EMA₂ = EMA(EMA₁, period)
              EMA₃ = EMA(EMA₂, period)
    
    ADVANCED TEMA (three periods):
        TEMA = 3×EMA₁ - 3×EMA₂ + EMA₃
        where EMA₁ = EMA(price, period)
              EMA₂ = EMA(EMA₁, period2)
              EMA₃ = EMA(EMA₂, period3)
    
    The TEMA reduces lag more than EMA or DEMA (Double EMA).
    More responsive to recent price changes while maintaining smoothness.
    
    Args:
        data: Input price data
        period: First EMA period (default 21)
        period2: Second EMA period (optional, defaults to period)
        period3: Third EMA period (optional, defaults to period)
    
    Returns:
        np.ndarray: TEMA values
    
    Examples:
        # Standard TEMA(21) - all three EMAs use period 21
        tema = calculate_tema(close_prices, period=21)
        
        # Advanced TEMA(13, 21, 34) - each EMA uses different period
        tema = calculate_tema(close_prices, period=13, period2=21, period3=34)
    
    References:
        - Created by Patrick Mulloy in 1994
        - Published in Technical Analysis of Stocks & Commodities magazine
        - Reduces lag by 3× compared to simple EMA
    """
    # Default to standard TEMA (all periods the same)
    if period2 is None:
        period2 = period
    if period3 is None:
        period3 = period
    
    # Calculate three successive EMAs
    ema1 = calculate_ema(data, period)
    ema2 = calculate_ema(ema1, period2)
    ema3 = calculate_ema(ema2, period3)
    
    # TEMA formula: 3×EMA₁ - 3×EMA₂ + EMA₃
    tema = 3 * ema1 - 3 * ema2 + ema3
    
    return tema


def calculate_tema_multi_period_grid(
    data: np.ndarray,
    period1_range: list = [8, 13, 21],
    period2_range: list = [13, 21, 34],
    period3_range: list = [21, 34, 55]
) -> dict:
    """
    Calculate TEMA for multiple period combinations (for optimization)
    
    WARNING: This generates N×M×K combinations which can be very large!
    Example: 3×3×3 = 27 combinations
             5×5×5 = 125 combinations
    
    Args:
        data: Input price data
        period1_range: List of periods for first EMA
        period2_range: List of periods for second EMA  
        period3_range: List of periods for third EMA
    
    Returns:
        dict: {(p1, p2, p3): tema_array}
    
    Example:
        results = calculate_tema_multi_period_grid(
            close_prices,
            period1_range=[8, 13, 21],
            period2_range=[13, 21, 34],
            period3_range=[21, 34, 55]
        )
        # Returns 27 different TEMA configurations
    """
    results = {}
    
    total_combos = len(period1_range) * len(period2_range) * len(period3_range)
    print(f"Calculating {total_combos} TEMA combinations...")
    
    combo_idx = 0
    for p1 in period1_range:
        for p2 in period2_range:
            for p3 in period3_range:
                # Skip invalid combinations (each period should be >= previous)
                if p1 <= p2 <= p3:
                    tema = calculate_tema(data, period=p1, period2=p2, period3=p3)
                    results[(p1, p2, p3)] = tema
                    combo_idx += 1
                    
                    if combo_idx % 10 == 0:
                        print(f"  Calculated {combo_idx}/{total_combos} combinations...")
    
    print(f"✓ Calculated {len(results)} valid TEMA combinations")
    return results


# Example usage and testing
if __name__ == "__main__":
    import matplotlib.pyplot as plt
    
    # Generate sample price data
    np.random.seed(42)
    n = 200
    prices = 100 + np.cumsum(np.random.randn(n) * 2)
    
    # Calculate standard TEMAs
    tema_8 = calculate_tema(prices, period=8)
    tema_21 = calculate_tema(prices, period=21)
    tema_55 = calculate_tema(prices, period=55)
    
    # Calculate advanced TEMA
    tema_custom = calculate_tema(prices, period=8, period2=21, period3=55)
    
    # Plot comparison
    plt.figure(figsize=(14, 8))
    
    plt.subplot(2, 1, 1)
    plt.plot(prices, label='Price', linewidth=2, alpha=0.7)
    plt.plot(tema_8, label='TEMA(8)', linewidth=1.5)
    plt.plot(tema_21, label='TEMA(21)', linewidth=1.5)
    plt.plot(tema_55, label='TEMA(55)', linewidth=1.5)
    plt.title('Standard TEMA Comparison (Single Period)')
    plt.legend()
    plt.grid(True, alpha=0.3)
    
    plt.subplot(2, 1, 2)
    plt.plot(prices, label='Price', linewidth=2, alpha=0.7)
    plt.plot(tema_21, label='TEMA(21, 21, 21)', linewidth=1.5)
    plt.plot(tema_custom, label='TEMA(8, 21, 55)', linewidth=1.5, linestyle='--')
    plt.title('Standard vs Advanced TEMA')
    plt.legend()
    plt.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('tema_comparison.png', dpi=150, bbox_inches='tight')
    print("✓ Saved tema_comparison.png")
    
    # Print statistics
    print("\nTEMA Responsiveness (lower = more responsive):")
    print(f"TEMA(8):  Mean lag from price = {np.mean(np.abs(prices[8:] - tema_8[8:])):.2f}")
    print(f"TEMA(21): Mean lag from price = {np.mean(np.abs(prices[21:] - tema_21[21:])):.2f}")
    print(f"TEMA(55): Mean lag from price = {np.mean(np.abs(prices[55:] - tema_55[55:])):.2f}")
    print(f"TEMA(8,21,55): Mean lag from price = {np.mean(np.abs(prices[55:] - tema_custom[55:])):.2f}")