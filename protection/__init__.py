"""
Bear market protection: SPY 200-day moving average regime detection

When SPY closes below its 200-day SMA the strategy exits faster
(config.BEAR_SELL_BANDWIDTH instead of config.SELL_BANDWIDTH; see
signals.signal_generator.get_sell_bandwidth).
"""

from .market_regime import bear_regime_series, detect_bear_regime

__all__ = ['bear_regime_series', 'detect_bear_regime']
