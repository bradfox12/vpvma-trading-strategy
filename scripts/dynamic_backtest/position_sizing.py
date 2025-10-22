"""
BPT (Behavioral Partitioning Theory) Position Sizing
Implements state-based position sizing based on trade history patterns

Three Binary States:
1. Previous Outcome: Win(1) / Loss(0)
2. Previous Score: Above Median(1) / Below Median(0)
3. Current Score: Above Median(1) / Below Median(0)

Creates 8 octants with different risk-adjusted performance
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional, Tuple
from dataclasses import dataclass


@dataclass
class TradeState:
    """
    3-binary state representation for BPT
    """
    prev_outcome: int  # 1=win, 0=loss
    prev_score_high: int  # 1=above median, 0=below
    cur_score_high: int  # 1=above median, 0=below
    
    def to_octant(self) -> int:
        """
        Convert state to octant index (0-7)
        
        Binary encoding: (prev_outcome)(prev_score_high)(cur_score_high)
        Example: Win(1) + HighScore(1) + HighScore(1) = 111 = octant 7
        """
        return (self.prev_outcome << 2) | (self.prev_score_high << 1) | self.cur_score_high
    
    def __str__(self):
        outcome = "W" if self.prev_outcome else "L"
        prev_score = "H" if self.prev_score_high else "L"
        cur_score = "H" if self.cur_score_high else "L"
        return f"({outcome}/{prev_score}→{cur_score})"


class BPTPositionSizer:
    """
    Behavioral Partitioning Theory position sizer
    
    Tracks performance by behavioral octant and allocates capital accordingly.
    Optimal octants get full size, unoptimal octants get reduced/zero size.
    
    Usage:
        sizer = BPTPositionSizer(base_size=0.05, optimal_threshold=1.8)
        
        # Calculate size for new trade
        sizing = sizer.calculate_position_size(
            symbol='AAPL',
            current_score=92,
            equity=100000
        )
        
        # After trade closes
        sizer.update_state(
            outcome=1,  # win
            score=92,
            pnl=2500,
            octant=sizing['octant']
        )
    """
    
    def __init__(
        self,
        base_size: float = 0.05,
        optimal_threshold: float = 1.8,
        min_samples: int = 10,
        rebalance_period: int = 50,
        score_median: float = 90.0,
        optimal_multiplier: float = 1.0,
        unoptimal_multiplier: float = 0.0
    ):
        """
        Initialize BPT position sizer
        
        Args:
            base_size: Base position size as fraction of equity (default 5%)
            optimal_threshold: PF threshold to classify octant as optimal
            min_samples: Minimum trades per octant before classification
            rebalance_period: Recompute optimal/unoptimal every N trades
            score_median: Initial score median for binary split
            optimal_multiplier: Size multiplier for optimal octants (1.0 = full size)
            unoptimal_multiplier: Size multiplier for unoptimal octants (0.0 = skip)
        """
        self.base_size = base_size
        self.optimal_threshold = optimal_threshold
        self.min_samples = min_samples
        self.rebalance_period = rebalance_period
        self.score_median = score_median
        self.optimal_multiplier = optimal_multiplier
        self.unoptimal_multiplier = unoptimal_multiplier
        
        # Octant statistics (8 buckets: 000 to 111)
        self.octant_stats = {
            i: {
                'wins': 0,
                'losses': 0,
                'gross_profit': 0.0,
                'gross_loss': 0.0,
                'n': 0
            } for i in range(8)
        }
        
        # Current optimal/unoptimal classification
        # Based on historical analysis: octants 1,5,6,7 are optimal
        self.optimal_octants = {1, 5, 6, 7}
        self.unoptimal_octants = {0, 2, 3, 4}
        
        # Trade history for state tracking
        self.last_outcome = None  # 1=win, 0=loss
        self.last_score = None
        self.trade_count = 0
        
        # Performance tracking
        self.total_optimal_trades = 0
        self.total_unoptimal_trades = 0
        self.skipped_trades = 0
    
    def calculate_position_size(
        self,
        symbol: str,
        current_score: float,
        equity: float,
        atr_pct: Optional[float] = None
    ) -> Dict:
        """
        Calculate position size based on BPT state
        
        Args:
            symbol: Stock symbol
            current_score: Current trend score (0-100)
            equity: Current portfolio equity
            atr_pct: Optional volatility for additional adjustment
            
        Returns:
            Dict with:
                'size': Position size in dollars
                'octant': Octant classification (0-7)
                'state': Human-readable state string
                'classification': 'OPTIMAL', 'UNOPTIMAL', 'INITIAL', or 'PROBE'
                'confidence': Confidence score (0-1)
                'octant_pf': Profit factor for this octant
                'octant_wr': Win rate for this octant
                'octant_n': Number of trades in this octant
                'size_multiplier': Actual multiplier applied
        """
        # Handle first trade (no previous state)
        if self.last_outcome is None:
            return {
                'size': self.base_size * equity,
                'octant': None,
                'state': 'INITIAL',
                'classification': 'INITIAL',
                'confidence': 1.0,
                'octant_pf': 0.0,
                'octant_wr': 0.0,
                'octant_n': 0,
                'size_multiplier': 1.0
            }
        
        # Build current state
        state = TradeState(
            prev_outcome=self.last_outcome,
            prev_score_high=1 if self.last_score > self.score_median else 0,
            cur_score_high=1 if current_score > self.score_median else 0
        )
        octant = state.to_octant()
        
        # Get octant statistics
        stats = self.octant_stats[octant]
        pf = self._calculate_pf(stats)
        wr = self._calculate_wr(stats)
        
        # Classify as optimal/unoptimal
        is_optimal = octant in self.optimal_octants
        
        # Determine size multiplier
        if is_optimal:
            size_multiplier = self.optimal_multiplier
            classification = 'OPTIMAL'
            self.total_optimal_trades += 1
        else:
            # Check if we should probe unoptimal octants
            if stats['n'] < 5:
                # Not enough data, use small probe
                size_multiplier = 0.3
                classification = 'PROBE'
            else:
                # Known unoptimal, use configured multiplier (default 0.0)
                size_multiplier = self.unoptimal_multiplier
                classification = 'UNOPTIMAL'
                if size_multiplier == 0.0:
                    self.skipped_trades += 1
            
            self.total_unoptimal_trades += 1
        
        # Optional volatility adjustment
        if atr_pct is not None:
            vol_adjustment = min(1.0, 3.0 / atr_pct)
            size_multiplier *= vol_adjustment
        
        # Calculate final size
        position_size = self.base_size * equity * size_multiplier
        
        # Confidence = how far above threshold (for optimal) or below (for unoptimal)
        if is_optimal:
            confidence = min(1.0, pf / self.optimal_threshold) if pf > 0 else 0.5
        else:
            confidence = max(0.0, 1.0 - pf / self.optimal_threshold) if pf > 0 else 0.5
        
        return {
            'size': position_size,
            'octant': octant,
            'state': str(state),
            'classification': classification,
            'confidence': confidence,
            'octant_pf': pf,
            'octant_wr': wr,
            'octant_n': stats['n'],
            'size_multiplier': size_multiplier
        }
    
    def update_state(
        self,
        outcome: int,
        score: float,
        pnl: float,
        octant: Optional[int] = None
    ):
        """
        Update state after trade closes
        
        Args:
            outcome: 1 if win (pnl > 0), 0 if loss (pnl <= 0)
            score: Trade entry score
            pnl: Trade P&L in dollars
            octant: Octant this trade belonged to
        """
        # Update octant statistics
        if octant is not None:
            stats = self.octant_stats[octant]
            stats['n'] += 1
            
            if outcome == 1:
                stats['wins'] += 1
                stats['gross_profit'] += abs(pnl)
            else:
                stats['losses'] += 1
                stats['gross_loss'] += abs(pnl)
        
        # Update state for next trade
        self.last_outcome = outcome
        self.last_score = score
        self.trade_count += 1
        
        # Rebalance octant classification periodically
        if self.trade_count % self.rebalance_period == 0:
            self._rebalance_octants()
    
    def _calculate_pf(self, stats: Dict) -> float:
        """Calculate profit factor for octant"""
        if stats['gross_loss'] == 0:
            return 999.0 if stats['gross_profit'] > 0 else 1.0
        return stats['gross_profit'] / stats['gross_loss']
    
    def _calculate_wr(self, stats: Dict) -> float:
        """Calculate win rate for octant"""
        if stats['n'] == 0:
            return 0.5
        return stats['wins'] / stats['n']
    
    def _rebalance_octants(self):
        """
        Recompute optimal vs unoptimal classification based on live data
        """
        octant_pfs = []
        
        for octant in range(8):
            stats = self.octant_stats[octant]
            if stats['n'] >= self.min_samples:
                pf = self._calculate_pf(stats)
                octant_pfs.append((octant, pf, stats['n']))
        
        if not octant_pfs:
            return
        
        # Sort by PF descending
        octant_pfs.sort(key=lambda x: x[1], reverse=True)
        
        # Reclassify: octants above threshold are optimal
        self.optimal_octants = set()
        for octant, pf, n in octant_pfs:
            if pf >= self.optimal_threshold:
                self.optimal_octants.add(octant)
        
        # Ensure at least top 3 are optimal (even if below threshold)
        if len(self.optimal_octants) < 3:
            for octant, pf, n in octant_pfs[:3]:
                self.optimal_octants.add(octant)
        
        self.unoptimal_octants = set(range(8)) - self.optimal_octants
        
        print(f"\n🔄 BPT Rebalance (Trade {self.trade_count}):")
        print(f"   Optimal octants: {sorted(self.optimal_octants)}")
        for octant in sorted(self.optimal_octants):
            stats = self.octant_stats[octant]
            pf = self._calculate_pf(stats)
            wr = self._calculate_wr(stats)
            print(f"     Octant {octant}: PF={pf:.2f}, WR={wr:.2%}, n={stats['n']}")
    
    def get_octant_report(self) -> pd.DataFrame:
        """
        Generate octant performance report
        
        Returns:
            DataFrame with octant statistics
        """
        rows = []
        for octant in range(8):
            stats = self.octant_stats[octant]
            pf = self._calculate_pf(stats)
            wr = self._calculate_wr(stats)
            
            rows.append({
                'octant': octant,
                'binary': f"{octant:03b}",
                'pf': pf,
                'wr': wr,
                'n': stats['n'],
                'wins': stats['wins'],
                'losses': stats['losses'],
                'gross_profit': stats['gross_profit'],
                'gross_loss': stats['gross_loss'],
                'classification': 'OPTIMAL' if octant in self.optimal_octants else 'UNOPTIMAL'
            })
        
        return pd.DataFrame(rows).sort_values('pf', ascending=False)
    
    def get_summary_stats(self) -> Dict:
        """
        Get summary statistics for BPT performance
        
        Returns:
            Dict with summary metrics
        """
        return {
            'total_trades': self.trade_count,
            'optimal_trades': self.total_optimal_trades,
            'unoptimal_trades': self.total_unoptimal_trades,
            'skipped_trades': self.skipped_trades,
            'optimal_pct': self.total_optimal_trades / max(1, self.trade_count) * 100,
            'skip_pct': self.skipped_trades / max(1, self.trade_count) * 100,
            'optimal_octants': sorted(self.optimal_octants),
            'unoptimal_octants': sorted(self.unoptimal_octants)
        }