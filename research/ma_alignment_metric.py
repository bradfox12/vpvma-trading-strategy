"""
MA Alignment Score
==================
Measures trend quality by checking moving average alignment

Score (0-3):
- +1 if Close > 20MA
- +1 if 20MA > 50MA
- +1 if 50MA > 200MA

Interpretation:
- Score 3: Perfect uptrend (all MAs aligned)
- Score 2: Good trend (most MAs aligned)
- Score 1: Weak trend
- Score 0: No trend / downtrend

Why it works for VPVMA:
- Clean MA alignment = smooth trends
- VPVMA performs best in smooth trending markets
- Avoids choppy stocks where MAs are tangled
"""

import numpy as np
import pandas as pd
from base_metric import BaseMetric


class MAAlignmentMetric(BaseMetric):
    """
    Moving Average Alignment Score - Trend Quality Indicator
    """
    
    def __init__(
        self,
        ma_short: int = 20,
        ma_medium: int = 50,
        ma_long: int = 200,
        lookback_days: int = 365
    ):
        """
        Initialize MA Alignment calculator
        
        Args:
            ma_short: Short-term MA period (default 20)
            ma_medium: Medium-term MA period (default 50)
            ma_long: Long-term MA period (default 200)
            lookback_days: Days of history needed
        """
        super().__init__(lookback_days=lookback_days)
        self.ma_short = ma_short
        self.ma_medium = ma_medium
        self.ma_long = ma_long
        self.name = f"MA_Alignment({ma_short},{ma_medium},{ma_long})"
    
    def get_description(self) -> str:
        return f"Moving average alignment score - trend quality (0-3)"
    
    def calculate(self, df: pd.DataFrame) -> pd.Series:
        """
        Calculate MA Alignment Score
        
        Args:
            df: DataFrame with OHLCV data
        
        Returns:
            Series with alignment scores (0-3)
        """
        df = df.copy()
        
        # Calculate moving averages
        df['ma_20'] = df['close'].rolling(window=self.ma_short).mean()
        df['ma_50'] = df['close'].rolling(window=self.ma_medium).mean()
        df['ma_200'] = df['close'].rolling(window=self.ma_long).mean()
        
        # Calculate alignment score
        score = 0
        
        # Condition 1: Close > 20MA
        score += (df['close'] > df['ma_20']).astype(int)
        
        # Condition 2: 20MA > 50MA
        score += (df['ma_20'] > df['ma_50']).astype(int)
        
        # Condition 3: 50MA > 200MA
        score += (df['ma_50'] > df['ma_200']).astype(int)
        
        return score
    
    def get_trend_description(self, score: float) -> str:
        """
        Get human-readable trend description
        
        Args:
            score: Alignment score (0-3)
        
        Returns:
            Description string
        """
        if pd.isna(score):
            return "Unknown"
        elif score == 3:
            return "Perfect uptrend (all MAs aligned)"
        elif score == 2:
            return "Good trend (most MAs aligned)"
        elif score == 1:
            return "Weak trend"
        else:
            return "No trend / Downtrend"


# Example usage and testing
if __name__ == "__main__":
    print("="*70)
    print("MA ALIGNMENT METRIC CALCULATOR TEST")
    print("="*70)
    
    # Create sample data - trending stock
    np.random.seed(42)
    dates = pd.date_range('2020-01-01', periods=300, freq='D')
    
    # Simulate strong uptrend
    trend = np.linspace(100, 200, 300)
    noise = np.random.randn(300) * 3
    close = trend + noise
    
    df = pd.DataFrame({
        'timestamp': dates,
        'open': close * 0.99,
        'high': close * 1.02,
        'low': close * 0.98,
        'close': close,
        'volume': np.random.randint(1000000, 5000000, 300)
    })
    
    # Calculate MA Alignment
    ma_calc = MAAlignmentMetric()
    df['ma_score'] = ma_calc.calculate(df)
    
    # Show results
    print("\n📊 Sample MA Alignment Calculation:")
    print(df[['timestamp', 'close', 'ma_score']].tail(20).to_string(index=False))
    
    # Statistics
    print(f"\n📈 Alignment Statistics (last 100 days):")
    recent_scores = df['ma_score'].tail(100)
    for score in [3, 2, 1, 0]:
        count = (recent_scores == score).sum()
        pct = count / len(recent_scores) * 100
        desc = ma_calc.get_trend_description(score)
        print(f"   Score {score}: {count} days ({pct:.1f}%) - {desc}")
    
    # Current status
    latest_score = df['ma_score'].iloc[-1]
    print(f"\n💡 Current MA Alignment: {latest_score}")
    print(f"   {ma_calc.get_trend_description(latest_score)}")
    
    if latest_score >= 2:
        print("   ✅ Good for VPVMA - clean trend")
    else:
        print("   ⚠️  Choppy - VPVMA may struggle")
    
    print("\n" + "="*70)
    print("MA ALIGNMENT METRIC READY ✅")
    print("="*70)