"""
VPVMA (Volume-Price Volatility Moving Average) Indicator
Main orchestration module implementing complete indicator calculation

Usage Example:
    import numpy as np
    from main import calculate_vpvma_indicator
    
    # Assuming you have OHLCV data
    result = calculate_vpvma_indicator(
        high=high_prices,
        low=low_prices,
        close=close_prices,
        open_price=open_prices,
        volume=volumes
    )
    
    vpvma_line = result['vpvma']
    signal_line = result['vpvmas']
    trading_signals = result['signals']  # 1=buy, -1=sell, 0=hold
"""

import numpy as np
from typing import Dict
from calculations import (
    calculate_typical_price,
    calculate_daily_volatility,
    calculate_svwma,
    calculate_lvwma,
    calculate_esvmap,
    calculate_elvmap,
    calculate_vpvma,
    calculate_vpvmas
)
from signals import generate_buy_signals, generate_sell_signals, combine_signals


def calculate_vpvma_indicator(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    open_price: np.ndarray,
    volume: np.ndarray
) -> Dict[str, np.ndarray]:
    """
    Calculate complete VPVMA indicator with trading signals
    
    Implements the full calculation sequence from the academic paper:
    1. Typical Price (TP) - Formula 4.2-1
    2. Short-term VWMA (SVWMA) - Formula 4.2-2
    3. Long-term VWMA (LVWMA) - Formula 4.2-3
    4. Daily Volatility (DV) - Formula 4.2-4
    5. Short-term EMA (ESVMap) - Formula 4.2-5
    6. Long-term EMA (ElVMap) - Formula 4.2-6
    7. VPVMA Line - Formula 4.2-7
    8. VPVMA Signal Line (VPVMAS) - Formula 4.2-8
    9. Buy/Sell Signals - Table 8 rules
    
    Args:
        high: Array of high prices
        low: Array of low prices
        close: Array of closing prices
        open_price: Array of opening prices
        volume: Array of trading volumes
    
    Returns:
        Dictionary containing:
            'vpvma': Main indicator line (np.ndarray)
            'vpvmas': Signal line (np.ndarray)
            'signals': Trading signals - 1=buy, -1=sell, 0=hold (np.ndarray)
            'buy_signals': Boolean array of buy signals (np.ndarray)
            'sell_signals': Boolean array of sell signals (np.ndarray)
    
    Note:
        - First ~35 periods will contain NaN values due to warmup period
        - Warmup = max(WINDOW_SLOW, WINDOW_FAST) + WINDOW_SIGN
        - Assumes input data is chronologically sorted
        - All arrays must be same length
    
    References:
        Academic paper formulas 4.2-1 through 4.2-8 and Table 8
    """
    # Step 1: Calculate Typical Price [Formula 4.2-1]
    tp = calculate_typical_price(high, low, close)
    
    # Step 2: Calculate Short-term VWMA [Formula 4.2-2]
    svwma = calculate_svwma(tp, volume)
    
    # Step 3: Calculate Long-term VWMA [Formula 4.2-3]
    lvwma = calculate_lvwma(tp, volume)
    
    # Step 4: Calculate Daily Volatility [Formula 4.2-4]
    dv = calculate_daily_volatility(high, low, close, open_price)
    
    # Step 5: Calculate ESVMap (short-term EMA) [Formula 4.2-5]
    esvmap = calculate_esvmap(svwma, dv)
    
    # Step 6: Calculate ElVMap (long-term EMA) [Formula 4.2-6]
    elvmap = calculate_elvmap(lvwma, dv)
    
    # Step 7: Calculate VPVMA Line [Formula 4.2-7]
    vpvma = calculate_vpvma(esvmap, elvmap)
    
    # Step 8: Calculate VPVMAS Signal Line [Formula 4.2-8]
    vpvmas = calculate_vpvmas(vpvma)
    
    # Step 9: Generate Buy Signals [Table 8]
    buy_signals = generate_buy_signals(vpvma, vpvmas)
    
    # Step 10: Generate Sell Signals [Table 8]
    sell_signals = generate_sell_signals(vpvma, vpvmas)
    
    # Step 11: Combine Signals
    signals = combine_signals(buy_signals, sell_signals)
    
    return {
        'vpvma': vpvma,
        'vpvmas': vpvmas,
        'signals': signals,
        'buy_signals': buy_signals,
        'sell_signals': sell_signals
    }


if __name__ == "__main__":
    # Example usage with dummy data
    print("VPVMA Indicator - Example Usage")
    print("-" * 50)
    
    # Generate sample data (replace with your actual OHLCV data)
    n = 100
    np.random.seed(42)
    
    sample_data = {
        'open': np.random.randn(n).cumsum() + 100,
        'high': np.random.randn(n).cumsum() + 102,
        'low': np.random.randn(n).cumsum() + 98,
        'close': np.random.randn(n).cumsum() + 100,
        'volume': np.random.randint(1000, 10000, n)
    }
    
    # Calculate indicator
    result = calculate_vpvma_indicator(
        high=sample_data['high'],
        low=sample_data['low'],
        close=sample_data['close'],
        open_price=sample_data['open'],
        volume=sample_data['volume']
    )
    
    # Display results
    print(f"VPVMA calculated for {n} periods")
    print(f"Valid signals start from index ~35 (warmup period)")
    print(f"\nBuy signals: {np.sum(result['buy_signals'])}")
    print(f"Sell signals: {np.sum(result['sell_signals'])}")
    print(f"\nFirst 5 valid VPVMA values:")
    print(result['vpvma'][35:40])