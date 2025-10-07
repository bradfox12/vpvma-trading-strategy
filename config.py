"""
VPVMA Indicator Configuration
Parameters from Table 8 of the academic paper
"""

# Window periods
WINDOW_FAST = 12  # Short-term period for SVWMA and ESVMap
WINDOW_SLOW = 26  # Long-term period for LVWMA and ElVMap
WINDOW_SIGN = 9   # Signal line period (SMA of VPVMA)

# Trading signal bandwidth
BANDWIDTH = 0.1   # Buy threshold: 1.1x, Sell threshold: 0.8x (asymmetric)