"""
Base Metric Class
=================
All metrics inherit from this base class for consistency
"""

import numpy as np
import pandas as pd
from abc import ABC, abstractmethod
from typing import Dict, Optional
from datetime import datetime, timedelta


class BaseMetric(ABC):
    """
    Base class for all universe selection metrics
    
    All metrics must implement:
    - calculate() method
    - name property
    - description property
    """
    
    def __init__(self, lookback_days: int = 365):
        """
        Initialize metric calculator
        
        Args:
            lookback_days: Days of history needed for calculation
        """
        self.lookback_days = lookback_days
        self.name = self.__class__.__name__
    
    @abstractmethod
    def calculate(self, df: pd.DataFrame) -> pd.Series:
        """
        Calculate metric values
        
        Args:
            df: DataFrame with OHLCV data (timestamp, open, high, low, close, volume)
        
        Returns:
            Series with metric values indexed by timestamp
        
        Must handle:
        - Missing data (NaN)
        - Insufficient data points
        - Edge cases (zero volume, etc.)
        """
        pass
    
    @abstractmethod
    def get_description(self) -> str:
        """Return human-readable description of metric"""
        pass
    
    def validate_data(self, df: pd.DataFrame, min_periods: int = 50) -> bool:
        """
        Validate that DataFrame has sufficient data
        
        Args:
            df: OHLCV DataFrame
            min_periods: Minimum required data points
        
        Returns:
            True if valid, False otherwise
        """
        if df is None or len(df) < min_periods:
            return False
        
        required_cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        if not all(col in df.columns for col in required_cols):
            return False
        
        return True
    
    def calculate_for_symbol(
        self,
        db,
        symbol: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        Calculate metric for a single symbol
        
        Args:
            db: Database instance
            symbol: Stock symbol
            start_date: Start date
            end_date: End date
        
        Returns:
            DataFrame with timestamp and metric value columns
        """
        try:
            # Fetch data with extra lookback for metric calculation
            fetch_start = start_date - timedelta(days=self.lookback_days)
            
            df = db.get_ohlcv_data(
                symbol=symbol,
                start_date=fetch_start,
                end_date=end_date
            )
            
            if not self.validate_data(df):
                return None
            
            # Calculate metric
            df = df.copy()
            df['metric_value'] = self.calculate(df)
            
            # Filter to requested date range
            df = df[df['timestamp'] >= start_date]
            
            # Return only timestamp and metric value
            result = df[['timestamp', 'metric_value']].copy()
            result['symbol'] = symbol
            
            return result
            
        except Exception as e:
            print(f"Error calculating {self.name} for {symbol}: {e}")
            return None
    
    def calculate_for_universe(
        self,
        db,
        symbols: list,
        start_date: datetime,
        end_date: datetime,
        batch_size: int = 50
    ) -> Dict[str, pd.DataFrame]:
        """
        Calculate metric for entire universe
        
        Args:
            db: Database instance
            symbols: List of stock symbols
            start_date: Start date
            end_date: End date
            batch_size: Process N symbols at a time
        
        Returns:
            Dictionary mapping symbol -> DataFrame with metric values
        """
        results = {}
        total = len(symbols)
        
        print(f"\nCalculating {self.name} for {total} symbols...")
        
        for i, symbol in enumerate(symbols):
            if (i + 1) % batch_size == 0 or (i + 1) == total:
                pct = ((i + 1) / total) * 100
                print(f"  Progress: {i+1}/{total} ({pct:.1f}%)", end='\r')
            
            result = self.calculate_for_symbol(db, symbol, start_date, end_date)
            
            if result is not None and len(result) > 0:
                results[symbol] = result
        
        print(f"\n✅ {self.name} calculated for {len(results)}/{total} symbols")
        
        return results
    
    def save_results(self, results: Dict[str, pd.DataFrame], output_path: str):
        """
        Save calculated metrics to CSV
        
        Args:
            results: Dictionary of symbol -> DataFrame
            output_path: Path to save CSV
        """
        if not results:
            print(f"⚠️  No results to save for {self.name}")
            return
        
        # Combine all symbols into single DataFrame
        all_data = []
        for symbol, df in results.items():
            all_data.append(df)
        
        combined = pd.concat(all_data, ignore_index=True)
        
        # Save to CSV
        combined.to_csv(output_path, index=False)
        print(f"✅ Saved {self.name} results to {output_path}")
        print(f"   Rows: {len(combined)}, Symbols: {combined['symbol'].nunique()}")


class MetricCalculator:
    """
    Convenience class for calculating multiple metrics at once
    """
    
    def __init__(self, metrics: list):
        """
        Initialize with list of metric instances
        
        Args:
            metrics: List of BaseMetric instances
        """
        self.metrics = metrics
    
    def calculate_all(
        self,
        db,
        symbols: list,
        start_date: datetime,
        end_date: datetime,
        output_dir: str
    ):
        """
        Calculate all metrics and save results
        
        Args:
            db: Database instance
            symbols: List of symbols
            start_date: Start date
            end_date: End date
            output_dir: Directory to save results
        """
        print(f"\n{'='*70}")
        print(f"CALCULATING {len(self.metrics)} METRICS FOR {len(symbols)} SYMBOLS")
        print(f"{'='*70}")
        print(f"Period: {start_date.date()} to {end_date.date()}")
        print(f"Output: {output_dir}")
        
        results_summary = []
        
        for i, metric in enumerate(self.metrics, 1):
            print(f"\n[{i}/{len(self.metrics)}] {metric.name}")
            print(f"{'='*70}")
            
            # Calculate metric
            results = metric.calculate_for_universe(
                db=db,
                symbols=symbols,
                start_date=start_date,
                end_date=end_date
            )
            
            # Save results
            output_file = f"{output_dir}/{metric.name.lower().replace(' ', '_')}.csv"
            metric.save_results(results, output_file)
            
            # Track summary
            results_summary.append({
                'metric': metric.name,
                'symbols_calculated': len(results),
                'total_symbols': len(symbols),
                'coverage': len(results) / len(symbols) * 100 if symbols else 0
            })
        
        # Print summary
        print(f"\n{'='*70}")
        print(f"CALCULATION COMPLETE")
        print(f"{'='*70}")
        
        summary_df = pd.DataFrame(results_summary)
        print(summary_df.to_string(index=False))
        
        return summary_df


# Example usage
if __name__ == "__main__":
    print("BaseMetric class loaded successfully")
    print("\nAll metric calculators should:")
    print("  1. Inherit from BaseMetric")
    print("  2. Implement calculate() method")
    print("  3. Implement get_description() method")
    print("  4. Handle edge cases (NaN, insufficient data, etc.)")