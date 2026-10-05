"""
Market Regime Detection - SPY 200-Day Moving Average
Identifies bear markets to trigger FastExit protection

Validation:
- Tested on 2019-2025 (7 years)
- Protection active ~9% of trading days (appropriate for bull-dominated period)
- Sharpe improvement: +0.152 in holdout test

Detection Logic:
- Bear Market: SPY close < SPY 200-day MA
- Bull Market: SPY close >= SPY 200-day MA
- Simple, robust, widely-used institutional standard
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging
import pandas as pd
import numpy as np
from datetime import timedelta

import config

logger = logging.getLogger(__name__)


def bear_regime_series(spy_data: pd.DataFrame, ma_period: int = None) -> pd.Series:
    """
    Vectorised regime for every SPY bar: True where close < SMA(close, ma_period).

    Bars without a full MA window are False (no protection), matching
    detect_bear_regime(). Indexed by spy_data['timestamp'].
    """
    if ma_period is None:
        ma_period = config.SPY_MA_PERIOD
    ma = spy_data['close'].rolling(window=ma_period, min_periods=ma_period).mean()
    bearish = (spy_data['close'] < ma) & ma.notna()
    return pd.Series(bearish.to_numpy(), index=pd.DatetimeIndex(spy_data['timestamp']))


def detect_bear_regime(
    db,
    current_date: str,
    ma_period: int = None,
    lookback_days: int = None
) -> bool:
    """
    Detect if market is in bear regime using SPY vs 200-day MA
    
    Args:
        db: Database instance with get_ohlcv_data() method
        current_date: Date to check regime (format: 'YYYY-MM-DD' or datetime)
        ma_period: Moving average period (default: config.SPY_MA_PERIOD)
        lookback_days: Calendar days of history to load
            (default: config.REGIME_LOOKBACK_DAYS, ~250 trading days)
    
    Returns:
        bool: True if SPY is below 200-day MA (bear market), False otherwise
    
    Examples:
        >>> from data.database import Database
        >>> db = Database()
        >>> 
        >>> # Check if we're in bear market
        >>> is_bear = detect_bear_regime(db, '2022-06-01')
        >>> print(f"Bear market: {is_bear}")
        >>> 
        >>> # Use in daily loop
        >>> for date in trading_dates:
        >>>     spy_bearish = detect_bear_regime(db, date)
        >>>     if spy_bearish:
        >>>         print(f"⚠️ Protection ON - {date}")
    
    Technical Details:
        - Uses SPY (S&P 500 ETF) as market proxy
        - Simple moving average (SMA) of close prices
        - Requires minimum 200 trading days of history
        - Fallback: Returns False (bull) if insufficient data
    """
 
    if ma_period is None:
        ma_period = config.SPY_MA_PERIOD
    if lookback_days is None:
        lookback_days = config.REGIME_LOOKBACK_DAYS

    current_date = pd.Timestamp(current_date)

    # Calculate start date for lookback period
    start_date = current_date - timedelta(days=lookback_days)
    
    try:
        # Fetch SPY data
        spy_data = db.get_ohlcv_data(
            symbol='SPY',
            start_date=start_date,
            end_date=current_date
        )
        
        # Validate data quality
        if spy_data is None or len(spy_data) < ma_period:
            logger.warning(
                "Insufficient SPY data for %s (%d bars, need %d) - defaulting to BULL regime",
                current_date.date(), 0 if spy_data is None else len(spy_data), ma_period
            )
            return False  # Default to bull (no protection) if data unavailable

        return bool(bear_regime_series(spy_data, ma_period).iloc[-1])

    except Exception:
        logger.exception("Error detecting regime for %s - defaulting to BULL regime", current_date)
        return False  # Default to bull on error
