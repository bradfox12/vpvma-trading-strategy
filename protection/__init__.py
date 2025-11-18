"""
Bear Market Protection System for VPVMA Strategy
Validated across 7 years (2019-2025) with significant performance improvement

Core Components:
- market_regime.py: SPY 200MA regime detection
- adaptive_bandwidth.py: Dynamic sell bandwidth adjustment

Validation Results (2024-2025 Holdout - 183 stocks):
- Sharpe: 0.977 → 1.129 (+15.5% improvement)
- CAGR: 12.73% → 14.82% (+2.09%)
- MaxDD: -23.95% → -23.12% (better risk control)

Usage:
    from protection import detect_bear_regime, get_adaptive_sell_bandwidth
    
    # Check if we're in bear market
    spy_bearish = detect_bear_regime(db, current_date)
    
    # Get appropriate sell bandwidth
    sell_bw = get_adaptive_sell_bandwidth(spy_bearish)
    
    # Generate sell signals with adaptive bandwidth
    sell_signals = generate_sell_signals(vpvma, vpvmas, sell_bandwidth=sell_bw)
"""

from .market_regime import detect_bear_regime
from .adaptive_bandwidth import get_adaptive_sell_bandwidth

__all__ = ['detect_bear_regime', 'get_adaptive_sell_bandwidth']