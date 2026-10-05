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

import json
import logging
from pathlib import Path

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Optional

import config
from data.database import Database
from strategy import rank_by_momentum

logger = logging.getLogger(__name__)

# Refuse to rebuild the universe when fewer than this fraction of qualified
# symbols have current data (e.g. the daily update only partly succeeded)
MIN_SCORED_FRACTION = 0.8


class UniverseSelector:
    """
    Selects top N stocks by momentum for VPVMA trading

    Rebalances monthly on the 1st trading day of each month.
    The selection is cached in memory and, if cache_file is given, on disk so
    separate daily runs within a month keep the same universe.
    """

    def __init__(
        self,
        db: Database,
        universe_size: int = None,
        momentum_period: int = None,
        min_data_days: int = None,  # Auto-calculated if not specified
        exclude_symbols: Optional[List[str]] = None,
        cache_file: Optional[Path] = None
    ):
        """
        Initialize universe selector

        Args:
            db: Database instance
            universe_size: Number of stocks to select (default: config.UNIVERSE_SIZE)
            momentum_period: Lookback period in bars (default: config.MOMENTUM_PERIOD)
            min_data_days: Minimum days of data required (default: momentum_period + 1)
            exclude_symbols: List of symbols to exclude (default: None)
            cache_file: JSON file persisting the monthly selection between runs
        """
        self.db = db
        self.universe_size = universe_size or config.UNIVERSE_SIZE
        self.momentum_period = momentum_period or config.MOMENTUM_PERIOD
        self.min_data_days = min_data_days if min_data_days is not None else (self.momentum_period + 1)
        self.exclude_symbols = exclude_symbols or []
        self.cache_file = Path(cache_file) if cache_file else None

        # Cache
        self._cached_universe = None
        self._cached_month = None
        self._cached_scores = None
        self._load_cache()

        # Get all qualified symbols once
        self._all_symbols = self._get_qualified_symbols()

        logger.info("UniverseSelector initialized: size=%d, momentum=%d bars, excluded=%s, qualified=%d",
                    self.universe_size, self.momentum_period, self.exclude_symbols, len(self._all_symbols))

    def _load_cache(self):
        if self.cache_file is None or not self.cache_file.exists():
            return
        try:
            data = json.loads(self.cache_file.read_text())
            self._cached_month = data['month']
            self._cached_universe = data['symbols']
            self._cached_scores = pd.DataFrame(data.get('scores', []),
                                               columns=['symbol', 'momentum_score', 'current_price', 'past_price'])
            logger.info("Loaded cached universe for %s (%d symbols) from %s",
                        self._cached_month, len(self._cached_universe), self.cache_file)
        except Exception:
            logger.exception("Could not read universe cache %s - will recalculate", self.cache_file)

    def _save_cache(self):
        if self.cache_file is None:
            return
        payload = {
            'month': self._cached_month,
            'symbols': self._cached_universe,
            'scores': self._cached_scores.to_dict('records') if self._cached_scores is not None else [],
            'saved_at': datetime.now().isoformat(timespec='seconds'),
        }
        tmp = self.cache_file.with_suffix('.tmp')
        tmp.write_text(json.dumps(payload, indent=2, default=float))
        tmp.replace(self.cache_file)

    def _get_qualified_symbols(self) -> List[str]:
        """
        Symbols with enough history for the indicator (INDICATOR_LOOKBACK_DAYS)
        and a bar within the last month, minus exclude_symbols
        """
        ranges = self.db.symbol_ranges()
        now = pd.Timestamp.now().normalize()
        ok = ((ranges['first'] <= now - timedelta(days=config.INDICATOR_LOOKBACK_DAYS))
              & (ranges['last'] >= now - timedelta(days=31)))
        excluded = set(self.exclude_symbols)
        return [sym for sym in ranges.loc[ok, 'symbol'] if sym not in excluded]

    def _calculate_momentum_scores(self, date: pd.Timestamp) -> pd.DataFrame:
        """
        Momentum scores for all qualified symbols using data up to `date`

        Returns:
            DataFrame [symbol, momentum_score, current_price, past_price], sorted descending
        """
        # 3x buffer: 20 trading days ~ 28 calendar days
        lookback_date = date - timedelta(days=self.momentum_period * 3)

        closes = {}
        failed = 0
        for symbol in self._all_symbols:
            try:
                df = self.db.get_ohlcv_data(symbol, start_date=lookback_date, end_date=date)
            except Exception:
                logger.exception("%s: failed to load data for momentum", symbol)
                failed += 1
                continue
            if len(df) >= self.min_data_days:
                closes[symbol] = df.set_index('timestamp')['close'].astype(float)

        scores = rank_by_momentum(closes, date, self.momentum_period, len(closes))
        logger.info("Momentum scored %d/%d symbols (%d load errors)",
                    len(scores), len(self._all_symbols), failed)
        return scores

    def _should_rebalance(self, date: pd.Timestamp) -> bool:
        """Rebalance when nothing is cached or the month has changed"""
        return self._cached_month is None or date.strftime('%Y-%m') != self._cached_month

    def get_universe(
        self,
        date: Optional[pd.Timestamp] = None,
        force_refresh: bool = False
    ) -> List[str]:
        """
        Get current universe of stocks to trade

        Returns the cached universe within the same month, otherwise ranks by
        momentum and selects the top N. If too few symbols have current data
        the previous universe is kept rather than trading on a partial ranking.
        """
        date = pd.Timestamp(date) if date is not None else pd.Timestamp.now()

        if not force_refresh and not self._should_rebalance(date):
            logger.info("Using cached universe (%s, %d symbols)", self._cached_month, len(self._cached_universe))
            return self._cached_universe

        current_month = date.strftime('%Y-%m')
        logger.info("Rebalancing universe for %s using data up to %s", current_month, date.date())

        momentum_df = self._calculate_momentum_scores(date)

        min_required = int(MIN_SCORED_FRACTION * len(self._all_symbols))
        if len(momentum_df) < min_required:
            logger.error(
                "Only %d/%d symbols have current data (need %d) - keeping previous universe (%s). "
                "Run the daily data update and retry.",
                len(momentum_df), len(self._all_symbols), min_required, self._cached_month
            )
            return self._cached_universe or []

        selected = momentum_df.head(self.universe_size)
        self._cached_universe = selected['symbol'].tolist()
        self._cached_month = current_month
        self._cached_scores = momentum_df
        self._save_cache()

        logger.info("Universe selected: %d stocks, momentum %.2f%% to %.2f%%, top 5 %s",
                    len(selected), selected['momentum_score'].iloc[-1] * 100,
                    selected['momentum_score'].iloc[0] * 100, self._cached_universe[:5])
        return self._cached_universe

    def get_momentum_scores(self) -> Optional[pd.DataFrame]:
        """Cached momentum scores [symbol, momentum_score, current_price, past_price]"""
        return self._cached_scores

    def get_universe_info(self) -> Dict:
        """Information about the current universe"""
        empty = {
            'size': 0,
            'cache_month': self._cached_month,
            'top_5': [],
            'momentum_range': None,
            'symbols': [],
            'median_momentum': None,
        }
        if not self._cached_universe:
            return empty

        scores_df = self._cached_scores
        if scores_df is None or scores_df.empty or 'symbol' not in scores_df:
            selected = pd.DataFrame(columns=['symbol', 'momentum_score'])
        else:
            selected = scores_df[scores_df['symbol'].isin(self._cached_universe)]

        return {
            'size': len(self._cached_universe),
            'cache_month': self._cached_month,
            'top_5': self._cached_universe[:5],
            'momentum_range': ((selected['momentum_score'].min(), selected['momentum_score'].max())
                               if len(selected) > 0 else None),
            'symbols': self._cached_universe,
            'median_momentum': selected['momentum_score'].median() if len(selected) > 0 else None,
        }

    def is_in_universe(self, symbol: str) -> bool:
        """True if symbol is in the current universe"""
        return bool(self._cached_universe) and symbol in self._cached_universe

    def get_symbol_rank(self, symbol: str) -> Optional[int]:
        """Rank of symbol in current universe (1 = highest momentum) or None"""
        if not self._cached_universe or symbol not in self._cached_universe:
            return None
        return self._cached_universe.index(symbol) + 1


# Example usage and testing
if __name__ == "__main__":
    from logging_setup import setup_logging
    setup_logging('universe_selector')
    print("="*80)
    print("UNIVERSE SELECTOR - TEST")
    print("="*80)
    
    # Initialize
    db = Database()
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
    
    print(f"\n✅ Universe Size: {info['size']} stocks")
    print(f"📅 Month: {info['cache_month']}")
    if info['momentum_range']:
        print(f"📊 Momentum Range: {info['momentum_range'][0]:.2%} to {info['momentum_range'][1]:.2%}")
    
    print(f"\n🏆 Top 10 Stocks:")
    for i, symbol in enumerate(universe[:10], 1):
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