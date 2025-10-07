"""
Signal generation package for VPVMA indicator
Implements buy/sell signal logic from Table 8
"""

from .signal_generator import generate_buy_signals, generate_sell_signals, combine_signals

__all__ = ['generate_buy_signals', 'generate_sell_signals', 'combine_signals']