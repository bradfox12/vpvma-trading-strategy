"""
ADX - Average Directional Index
================================
Measures trend strength WITHOUT direction bias

Formula:
1. Calculate +DM and -DM (directional movement)
2. Calculate +DI and -DI (directional indicators)
3. Calculate DX (directional index)
4. Calculate ADX (smoothed DX)

Interpretation:
- ADX > 25: Strong trend (good for VPVMA)
- ADX 20-25: Moderate trend
- ADX < 20: Weak/choppy (VPVMA struggles here)

References:
- Created by J. Welles Wilder
- Industry standard for trend strength
"""

import numpy as np
import pandas as pd
from base_metric import BaseMetric


class ADXMetric(BaseMetric):
    """
    Average Directional Index - Trend Strength Indicator
    """
    
    def __init__(self, period: int = 14, lookback_days: int = 365):
        """
        Initialize ADX calculator
        
        Args:
            period: ADX smoothing period (default 14, Wilder's original)
            lookback_days: Days of history needed
        """
        super().__init__(lookback_days=lookback_days)
        self.period = period
        self.name = f"ADX({period})"
    
    def get_description(self) -> str:
        return f"Average Directional Index - trend strength (period={self.period})"
    
    def calculate(self, df: pd.DataFrame) -> pd.Series:
        """
        Calculate ADX
        
        Args:
            df: DataFrame with OHLCV data
        
        Returns:
            Series with ADX values
        """
        df = df.copy()
        
        # Step 1: Calculate True Range (TR)
        df['tr'] = self._calculate_true_range(df)
        
        # Step 2: Calculate Directional Movement (+DM and -DM)
        df['+dm'], df['-dm'] = self._calculate_directional_movement(df)
        
        # Step 3: Calculate smoothed TR, +DM, -DM
        df['atr'] = self._smooth(df['tr'], self.period)
        df['+dm_smooth'] = self._smooth(df['+dm'], self.period)
        df['-dm_smooth'] = self._smooth(df['-dm'], self.period)
        
        # Step 4: Calculate Directional Indicators (+DI and -DI)
        df['+di'] = 100 * df['+dm_smooth'] / df['atr']
        df['-di'] = 100 * df['-dm_smooth'] / df['atr']
        
        # Step 5: Calculate DX (Directional Index)
        df['dx'] = 100 * np.abs(df['+di'] - df['-di']) / (df['+di'] + df['-di'])
        
        # Step 6: Calculate ADX (smoothed DX)
        df['adx'] = self._smooth(df['dx'], self.period)
        
        return df['adx']
    
    def _calculate_true_range(self, df: pd.DataFrame) -> pd.Series:
        """
        Calculate True Range
        
        TR = max(high - low, abs(high - prev_close), abs(low - prev_close))
        """
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift(1))
        low_close = np.abs(df['low'] - df['close'].shift(1))
        
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        
        return tr
    
    def _calculate_directional_movement(self, df: pd.DataFrame) -> tuple:
        """
        Calculate +DM and -DM
        
        +DM = high - prev_high (if positive and > down_move)
        -DM = prev_low - low (if positive and > up_move)
        """
        up_move = df['high'] - df['high'].shift(1)
        down_move = df['low'].shift(1) - df['low']
        
        # +DM: up move that's larger than down move
        plus_dm = np.where(
            (up_move > down_move) & (up_move > 0),
            up_move,
            0
        )
        
        # -DM: down move that's larger than up move
        minus_dm = np.where(
            (down_move > up_move) & (down_move > 0),
            down_move,
            0
        )
        
        return pd.Series(plus_dm, index=df.index), pd.Series(minus_dm, index=df.index)
    
    def _smooth(self, series: pd.Series, period: int) -> pd.Series:
        """
        Wilder's smoothing (similar to EMA but different)
        
        First value: Simple average of first N periods
        Subsequent: Prior smoothed value - (Prior / period) + Current value
        
        This is Wilder's original smoothing method
        """
        result = pd.Series(index=series.index, dtype=float)
        
        # First smoothed value is simple average
        result.iloc[period - 1] = series.iloc[:period].mean()
        
        # Subsequent values use Wilder's smoothing
        for i in range(period, len(series)):
            if pd.notna(result.iloc[i - 1]) and pd.notna(series.iloc[i]):
                result.iloc[i] = (
                    result.iloc[i - 1] * (period - 1) + series.iloc[i]
                ) / period
        
        return result


# Example usage and testing
if __name__ == "__main__":
    print("="*70)
    print("ADX METRIC CALCULATOR TEST")
    print("="*70)
    
    # Create sample data
    np.random.seed(42)
    dates = pd.date_range('2020-01-01', periods=200, freq='D')
    
    # Simulate trending stock
    trend = np.linspace(100, 150, 200)
    noise = np.random.randn(200) * 2
    close = trend + noise
    
    df = pd.DataFrame({
        'timestamp': dates,
        'open': close * 0.99,
        'high': close * 1.02,
        'low': close * 0.98,
        'close': close,
        'volume': np.random.randint(1000000, 5000000, 200)
    })
    
    # Calculate ADX
    adx_calc = ADXMetric(period=14)
    df['adx'] = adx_calc.calculate(df)
    
    # Show results
    print("\n📊 Sample ADX Calculation:")
    print(df[['timestamp', 'close', 'adx']].tail(10).to_string(index=False))
    
    # Interpret
    latest_adx = df['adx'].iloc[-1]
    print(f"\n💡 Latest ADX: {latest_adx:.2f}")
    
    if latest_adx > 25:
        print("   ✅ STRONG TREND - Good for VPVMA!")
    elif latest_adx > 20:
        print("   ⚠️  MODERATE TREND")
    else:
        print("   ❌ WEAK/CHOPPY - VPVMA will struggle")
    
    print("\n" + "="*70)
    print("ADX METRIC READY ✅")
    print("="*70)