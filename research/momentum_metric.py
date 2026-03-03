"""
Price Momentum
==============
Simple percentage change over specified period

Formula:
Momentum = (Close - Close_N_days_ago) / Close_N_days_ago

Interpretation:
- Positive momentum: Price is rising
- Negative momentum: Price is falling
- Magnitude: How fast price is changing

Why it works for VPVMA:
- VPVMA is a momentum indicator
- Works best when stocks have clear momentum
- Positive momentum = clear uptrend (VPVMA's sweet spot)
"""

import numpy as np
import pandas as pd
from base_metric import BaseMetric


class MomentumMetric(BaseMetric):
    """
    Price Momentum - Simple percentage change
    """
    
    def __init__(self, period: int = 20, lookback_days: int = 365):
        """
        Initialize Momentum calculator
        
        Args:
            period: Lookback period in days (default 20)
            lookback_days: Days of history needed
        """
        super().__init__(lookback_days=lookback_days)
        self.period = period
        self.name = f"Momentum({period}d)"
    
    def get_description(self) -> str:
        return f"{self.period}-day price momentum (percentage change)"
    
    def calculate(self, df: pd.DataFrame) -> pd.Series:
        """
        Calculate momentum
        
        Args:
            df: DataFrame with OHLCV data
        
        Returns:
            Series with momentum values (as decimals, e.g. 0.05 = 5%)
        """
        df = df.copy()
        
        # Calculate percentage change
        momentum = df['close'].pct_change(periods=self.period)
        
        return momentum
    
    def get_momentum_description(self, momentum: float) -> str:
        """
        Get human-readable momentum description
        
        Args:
            momentum: Momentum value (decimal)
        
        Returns:
            Description string
        """
        if pd.isna(momentum):
            return "Unknown"
        
        momentum_pct = momentum * 100
        
        if momentum_pct > 20:
            return f"Very Strong Up ({momentum_pct:.1f}%)"
        elif momentum_pct > 10:
            return f"Strong Up ({momentum_pct:.1f}%)"
        elif momentum_pct > 5:
            return f"Moderate Up ({momentum_pct:.1f}%)"
        elif momentum_pct > 0:
            return f"Weak Up ({momentum_pct:.1f}%)"
        elif momentum_pct > -5:
            return f"Weak Down ({momentum_pct:.1f}%)"
        elif momentum_pct > -10:
            return f"Moderate Down ({momentum_pct:.1f}%)"
        elif momentum_pct > -20:
            return f"Strong Down ({momentum_pct:.1f}%)"
        else:
            return f"Very Strong Down ({momentum_pct:.1f}%)"


class MultiPeriodMomentum(BaseMetric):
    """
    Multi-period momentum - combines multiple timeframes
    
    Useful for detecting momentum acceleration/deceleration
    """
    
    def __init__(
        self,
        periods: list = [5, 10, 20, 50],
        lookback_days: int = 365
    ):
        """
        Initialize multi-period momentum calculator
        
        Args:
            periods: List of momentum periods to calculate
            lookback_days: Days of history needed
        """
        super().__init__(lookback_days=lookback_days)
        self.periods = periods
        self.name = "Multi_Period_Momentum"
    
    def get_description(self) -> str:
        return f"Average momentum across {len(self.periods)} periods"
    
    def calculate(self, df: pd.DataFrame) -> pd.Series:
        """
        Calculate average momentum across multiple periods
        
        Args:
            df: DataFrame with OHLCV data
        
        Returns:
            Series with average momentum values
        """
        df = df.copy()
        
        # Calculate momentum for each period
        momentums = []
        for period in self.periods:
            mom = df['close'].pct_change(periods=period)
            momentums.append(mom)
        
        # Average across all periods
        avg_momentum = pd.concat(momentums, axis=1).mean(axis=1)
        
        return avg_momentum


# Example usage and testing
if __name__ == "__main__":
    print("="*70)
    print("MOMENTUM METRIC CALCULATOR TEST")
    print("="*70)
    
    # Create sample data - trending stock
    np.random.seed(42)
    dates = pd.date_range('2020-01-01', periods=200, freq='D')
    
    # Simulate stock with momentum
    base_price = 100
    momentum_values = []
    price = base_price
    
    for i in range(200):
        # Simulate trending behavior
        if i < 100:
            daily_change = np.random.randn() * 0.5 + 0.3  # Uptrend
        else:
            daily_change = np.random.randn() * 0.5 - 0.1  # Pullback
        
        price *= (1 + daily_change / 100)
        momentum_values.append(price)
    
    df = pd.DataFrame({
        'timestamp': dates,
        'open': momentum_values,
        'high': [p * 1.02 for p in momentum_values],
        'low': [p * 0.98 for p in momentum_values],
        'close': momentum_values,
        'volume': np.random.randint(1000000, 5000000, 200)
    })
    
    # Calculate momentum
    mom_calc = MomentumMetric(period=20)
    df['momentum_20d'] = mom_calc.calculate(df)
    
    # Show results
    print("\n📊 Sample 20-Day Momentum Calculation:")
    result_df = df[['timestamp', 'close', 'momentum_20d']].tail(10).copy()
    result_df['momentum_pct'] = result_df['momentum_20d'] * 100
    print(result_df[['timestamp', 'close', 'momentum_pct']].to_string(index=False))
    
    # Current status
    latest_momentum = df['momentum_20d'].iloc[-1]
    print(f"\n💡 Current 20-Day Momentum: {latest_momentum*100:.2f}%")
    print(f"   {mom_calc.get_momentum_description(latest_momentum)}")
    
    if latest_momentum > 0.05:
        print("   ✅ Strong positive momentum - Good for VPVMA!")
    elif latest_momentum > 0:
        print("   ⚠️  Weak positive momentum")
    else:
        print("   ❌ Negative momentum - VPVMA may struggle")
    
    # Test multi-period momentum
    print(f"\n{'='*70}")
    print("MULTI-PERIOD MOMENTUM TEST")
    print(f"{'='*70}")
    
    multi_mom = MultiPeriodMomentum(periods=[5, 10, 20, 50])
    df['multi_momentum'] = multi_mom.calculate(df)
    
    print("\n📊 Multi-Period vs Single-Period:")
    comp_df = df[['timestamp', 'momentum_20d', 'multi_momentum']].tail(5).copy()
    comp_df['momentum_20d_pct'] = comp_df['momentum_20d'] * 100
    comp_df['multi_momentum_pct'] = comp_df['multi_momentum'] * 100
    print(comp_df[['timestamp', 'momentum_20d_pct', 'multi_momentum_pct']].to_string(index=False))
    
    print("\n" + "="*70)
    print("MOMENTUM METRIC READY ✅")
    print("="*70)