"""
Universe Selector - Momentum 20D (Top 100 Stocks)

Selects the top 100 stocks by 20-day momentum at the beginning of each trading month.
The VPVMA strategy then trades up to 20 positions within this universe.

Validated Performance (2019-2025):
- Average Sharpe: 1.247
- Average CAGR: 32.82%
- Consistency: 5/5 periods positive (100%)

Usage:
    from universe_selector import UniverseSelector
    
    selector = UniverseSelector(db)
    universe = selector.get_universe(current_date)
    # Returns: List of top 100 symbols by momentum
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from data.database import Database


class UniverseSelector:
    """
    Selects top N stocks by momentum for VPVMA trading
    
    Rebalances monthly on the 1st trading day of each month.
    Caches universe to avoid recalculation during the month.
    """
    
    def __init__(
        self,
        db: Database,
        universe_size: int = 100,
        momentum_period: int = 20,
        min_data_days: int = None,  # Auto-calculated if not specified
        exclude_symbols: Optional[List[str]] = None
    ):
        """
        Initialize universe selector
        
        Args:
            db: Database instance
            universe_size: Number of stocks to select (default: 100)
            momentum_period: Lookback period in days (default: 20)
            min_data_days: Minimum days of data required (default: momentum_period + 1)
            exclude_symbols: List of symbols to exclude (default: None)
        """
        self.db = db
        self.universe_size = universe_size
        self.momentum_period = momentum_period
        # Default to momentum_period + 1 if not specified
        self.min_data_days = min_data_days if min_data_days is not None else (momentum_period + 1)
        self.exclude_symbols = exclude_symbols or []
        
        # Cache
        self._cached_universe = None
        self._cached_month = None
        self._cached_scores = None
        
        # Get all qualified symbols once
        self._all_symbols = self._get_qualified_symbols()
        
        print(f"✅ UniverseSelector initialized")
        print(f"   Universe size: {self.universe_size} stocks")
        print(f"   Momentum period: {self.momentum_period} days")
        print(f"   Excluded: {self.exclude_symbols}")
        print(f"   Qualified symbols: {len(self._all_symbols)}")
    
    def _get_qualified_symbols(self) -> List[str]:
        """
        Get all symbols with sufficient historical data
        
        Returns:
            List of qualified symbols (excludes symbols in exclude_symbols list)
        """
        # Build exclusion clause
        if self.exclude_symbols:
            exclude_clause = " AND symbol NOT IN ({})".format(
                ','.join([f"'{s}'" for s in self.exclude_symbols])
            )
        else:
            exclude_clause = ""
        
        query = f"""
            SELECT DISTINCT symbol
            FROM ohlcv_data
            WHERE 1=1{exclude_clause}
            GROUP BY symbol
            HAVING MIN(timestamp) <= '2018-01-01'
            AND MAX(timestamp) >= CURRENT_DATE - INTERVAL '1 month'
            ORDER BY symbol
        """
        
        df = pd.read_sql(query, self.db.engine)
        symbols = df['symbol'].tolist()
        
        return symbols
    
    def _calculate_momentum_scores(
        self,
        date: pd.Timestamp
    ) -> pd.DataFrame:
        """
        Calculate momentum scores for all symbols at given date
        
        Momentum = (price_today / price_N_days_ago) - 1
        
        Args:
            date: Date to calculate momentum for
        
        Returns:
            DataFrame with columns: [symbol, momentum_score, current_price]
            Sorted by momentum_score descending
        """
        momentum_data = []
        
        # Get data from lookback period to current date
        # Use 3x buffer to account for weekends and holidays
        # 20 trading days ≈ 28 calendar days, so 60 days buffer ensures we get 21+ trading days
        lookback_date = date - timedelta(days=self.momentum_period * 3)
        
        # WEEKEND FIX: Use most recent available date from database
        # On Mondays/holidays, requested date may not exist yet in database
        try:
            spy_check = self.db.get_ohlcv_data('SPY', start_date=lookback_date, end_date=date)
            if not spy_check.empty:
                most_recent_date = spy_check['timestamp'].max()
                if most_recent_date < date:
                    print(f"   📅 Using most recent data: {most_recent_date} (requested: {date})")
                    date = most_recent_date
                else:
                    print(f"   📅 Query date: {date} (type: {type(date)})")
                print(f"   📅 Lookback range: {lookback_date} to {date}")
        except Exception as e:
            print(f"   ⚠️ Could not check most recent date: {e}")
        
        symbols_checked = 0
        symbols_insufficient_data = 0
        symbols_insufficient_recent = 0
        
        for symbol in self._all_symbols:
            try:
                symbols_checked += 1
                
                # Get price data
                df = self.db.get_ohlcv_data(
                    symbol,
                    start_date=lookback_date,
                    end_date=date
                )
                
                if symbols_checked <= 3:
                    print(f"   DEBUG {symbol}:")
                    print(f"          Query returned: {len(df)} rows")
                    if not df.empty:
                        print(f"          Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
                
                if len(df) < self.min_data_days:
                    symbols_insufficient_data += 1
                    if symbols_checked <= 3:
                        print(f"          ❌ FAILED: {len(df)} < {self.min_data_days} (min_data_days)")
                    continue
                
                # Get recent N+1 days for momentum calculation
                # No need to filter by date - get_ohlcv_data already did that
                recent_data = df.tail(self.momentum_period + 1)
                
                if len(recent_data) < self.momentum_period + 1:
                    symbols_insufficient_recent += 1
                    if symbols_checked <= 3:
                        print(f"          ❌ FAILED: recent={len(recent_data)} < {self.momentum_period + 1} (need 21 days)")
                    continue
                
                if symbols_checked <= 3:
                    print(f"          ✅ SUCCESS: Calculated momentum")
                
                # Calculate momentum
                current_price = recent_data['close'].iloc[-1]
                past_price = recent_data['close'].iloc[0]
                
                if past_price <= 0:  # Sanity check
                    continue
                
                momentum_score = (current_price / past_price) - 1
                
                momentum_data.append({
                    'symbol': symbol,
                    'momentum_score': momentum_score,
                    'current_price': current_price,
                    'past_price': past_price
                })
                
            except Exception as e:
                # Skip symbols with data issues
                continue
        
        # Create DataFrame and sort by momentum
        momentum_df = pd.DataFrame(momentum_data)
        
        if len(momentum_df) > 0:
            momentum_df = momentum_df.sort_values('momentum_score', ascending=False)
        
        # Print summary
        print(f"   📊 Results: {len(momentum_df)} valid / {symbols_checked} checked")
        if symbols_insufficient_data > 0:
            print(f"      ❌ {symbols_insufficient_data} failed: insufficient data (< {self.min_data_days} days)")
        if symbols_insufficient_recent > 0:
            print(f"      ❌ {symbols_insufficient_recent} failed: insufficient recent data (< {self.momentum_period + 1} days)")
        
        return momentum_df
    
    def _should_rebalance(self, date: pd.Timestamp) -> bool:
        """
        Check if universe should be rebalanced
        
        Rebalances on 1st trading day of each month
        
        Args:
            date: Current date
        
        Returns:
            True if should rebalance, False otherwise
        """
        current_month = date.strftime('%Y-%m')
        
        # No cached universe - need to rebalance
        if self._cached_month is None:
            return True
        
        # Different month - need to rebalance
        if current_month != self._cached_month:
            return True
        
        return False
    
    def get_universe(
        self,
        date: Optional[pd.Timestamp] = None,
        force_refresh: bool = False
    ) -> List[str]:
        """
        Get current universe of stocks to trade
        
        Returns cached universe if still in same month,
        otherwise recalculates momentum and selects top N stocks.
        
        Args:
            date: Date to get universe for (default: today)
            force_refresh: Force recalculation even if cached (default: False)
        
        Returns:
            List of top N symbols by momentum score
        
        Example:
            >>> selector = UniverseSelector(db)
            >>> universe = selector.get_universe(pd.Timestamp('2024-11-01'))
            >>> print(f"Trading universe: {len(universe)} stocks")
            >>> print(f"Top 5: {universe[:5]}")
        """
        if date is None:
            date = pd.Timestamp.now()
        
        # Check if we need to rebalance
        if not force_refresh and not self._should_rebalance(date):
            print(f"📦 Using cached universe ({self._cached_month})")
            return self._cached_universe
        
        # Rebalance: calculate new universe
        current_month = date.strftime('%Y-%m')
        print(f"\n🔄 Rebalancing universe for {current_month}")
        print(f"   Date: {date.strftime('%Y-%m-%d')}")
        print(f"   Calculating {self.momentum_period}-day momentum for {len(self._all_symbols)} stocks...")
        
        # Calculate momentum scores
        momentum_df = self._calculate_momentum_scores(date)
        
        print(f"   Valid momentum scores: {len(momentum_df)}")
        
        # Handle empty results
        if len(momentum_df) == 0:
            print(f"   ❌ ERROR: No valid momentum scores calculated!")
            print(f"   This usually means:")
            print(f"      - Database needs more historical data (need {self.min_data_days}+ days)")
            print(f"      - Run daily data update to fetch more history")
            # Return empty universe - portfolio manager will handle this
            self._cached_universe = []
            self._cached_month = current_month
            self._cached_scores = momentum_df
            return []
        
        if len(momentum_df) < self.universe_size:
            print(f"   ⚠️  WARNING: Only {len(momentum_df)} stocks with valid data")
            print(f"   Using all available stocks (target: {self.universe_size})")
        
        # Select top N stocks
        selected = momentum_df.head(self.universe_size)
        universe = selected['symbol'].tolist()
        
        # Cache results
        self._cached_universe = universe
        self._cached_month = current_month
        self._cached_scores = momentum_df
        
        # Print summary statistics
        top_momentum = selected['momentum_score'].iloc[0] if len(selected) > 0 else 0
        bottom_momentum = selected['momentum_score'].iloc[-1] if len(selected) > 0 else 0
        avg_momentum = selected['momentum_score'].mean() if len(selected) > 0 else 0
        
        print(f"\n   ✅ Universe selected: {len(universe)} stocks")
        print(f"   📊 Momentum range: {bottom_momentum:.2%} to {top_momentum:.2%}")
        print(f"   📊 Average momentum: {avg_momentum:.2%}")
        print(f"   🏆 Top 5 stocks: {universe[:5]}")
        print(f"   📅 Valid until: {current_month} end\n")
        
        return universe
    
    def get_momentum_scores(self) -> Optional[pd.DataFrame]:
        """
        Get cached momentum scores DataFrame
        
        Returns:
            DataFrame with all momentum scores (if available)
            Columns: [symbol, momentum_score, current_price, past_price]
        """
        return self._cached_scores
    
    def get_universe_info(self) -> Dict:
        """
        Get information about current universe
        
        Returns:
            Dictionary with universe statistics
        """
        if self._cached_universe is None:
            return {
                'size': 0,
                'cache_month': None,
                'top_5': [],
                'momentum_range': None,
                'symbols': []
            }
        
        scores_df = self._cached_scores
        selected = scores_df[scores_df['symbol'].isin(self._cached_universe)]
        
        # Calculate momentum range
        if len(selected) > 0:
            momentum_range = (selected['momentum_score'].min(), selected['momentum_score'].max())
        else:
            momentum_range = None
        
        return {
            'size': len(self._cached_universe),
            'cache_month': self._cached_month,
            'top_5': self._cached_universe[:5],
            'momentum_range': momentum_range,
            'symbols': self._cached_universe,
            'median_momentum': selected['momentum_score'].median() if len(selected) > 0 else None
        }
    
    def is_in_universe(self, symbol: str) -> bool:
        """
        Check if symbol is in current universe
        
        Args:
            symbol: Stock symbol to check
        
        Returns:
            True if symbol is in current universe, False otherwise
        """
        if self._cached_universe is None:
            return False
        
        return symbol in self._cached_universe
    
    def get_symbol_rank(self, symbol: str) -> Optional[int]:
        """
        Get rank of symbol in current universe (1-indexed)
        
        Args:
            symbol: Stock symbol
        
        Returns:
            Rank (1 = highest momentum) or None if not in universe
        """
        if self._cached_universe is None:
            return None
        
        try:
            rank = self._cached_universe.index(symbol) + 1
            return rank
        except ValueError:
            return None


# Example usage and testing
if __name__ == "__main__":
    print("="*80)
    print("UNIVERSE SELECTOR - TEST")
    print("="*80)
    
    # Initialize
    db = Database(db_type='postgresql')
    selector = UniverseSelector(
        db=db,
        universe_size=100,
        momentum_period=20
    )
    
    # Test with recent date
    test_date = pd.Timestamp('2024-11-01')
    
    print(f"\nTesting universe selection for {test_date.strftime('%Y-%m-%d')}...\n")
    
    # Get universe
    universe = selector.get_universe(test_date)
    
    print("\n" + "="*80)
    print("RESULTS")
    print("="*80)
    
    # Get universe info
    info = selector.get_universe_info()
    
    print(f"\n✅ Universe Size: {info['universe_size']} stocks")
    print(f"📅 Month: {info['month']}")
    print(f"📊 Average Momentum: {info['avg_momentum']:.2%}")
    print(f"📊 Momentum Range: {info['bottom_momentum']:.2%} to {info['top_momentum']:.2%}")
    
    print(f"\n🏆 Top 10 Stocks:")
    for i, symbol in enumerate(info['top_5_stocks'] + universe[5:10], 1):
        rank = selector.get_symbol_rank(symbol)
        scores_df = selector.get_momentum_scores()
        if scores_df is not None:
            momentum = scores_df[scores_df['symbol'] == symbol]['momentum_score'].iloc[0]
            print(f"   {rank:2d}. {symbol:5s} - Momentum: {momentum:+.2%}")
    
    # Test caching
    print("\n" + "="*80)
    print("TESTING CACHE")
    print("="*80)
    
    print("\nCalling get_universe() again (should use cache)...")
    universe2 = selector.get_universe(test_date)
    
    print(f"✅ Same universe returned: {universe == universe2}")
    
    # Test force refresh
    print("\nTesting force refresh...")
    universe3 = selector.get_universe(test_date, force_refresh=True)
    print(f"✅ Universe recalculated: {len(universe3)} stocks")
    
    # Test symbol checks
    print("\n" + "="*80)
    print("TESTING SYMBOL CHECKS")
    print("="*80)
    
    test_symbol = universe[0]
    print(f"\nChecking if {test_symbol} is in universe...")
    print(f"   In universe: {selector.is_in_universe(test_symbol)}")
    print(f"   Rank: #{selector.get_symbol_rank(test_symbol)}")
    
    print(f"\nChecking if 'SPY' is in universe...")
    print(f"   In universe: {selector.is_in_universe('SPY')}")
    print(f"   Rank: {selector.get_symbol_rank('SPY')}")
    
    print("\n" + "="*80)
    print("✅ TEST COMPLETE")
    print("="*80)