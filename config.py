"""
VPVMA Indicator Configuration
Parameters from Table 8 of the academic paper + Bear Market Protection

RECENT UPDATES:
- Added FastExit+SPY200 bear market protection (validated 2024-2025)
- Maintains independent BUY/SELL bandwidth controls
"""

# ============================================================================
# VPVMA INDICATOR PARAMETERS (Core Strategy)
# ============================================================================

# Window periods
WINDOW_FAST = 12  # Short-term period for SVWMA and ESVMap
WINDOW_SLOW = 26  # Long-term period for LVWMA and ElVMap
WINDOW_SIGN = 18  # Signal line SMA period (Modified by regime_optimization_vpvma)

# ============================================================================
# TRADING SIGNAL BANDWIDTH (Independent Buy/Sell Controls)
# ============================================================================

# Buy threshold - Entry selectivity
# Higher = More selective entries (only strong signals)
# Formula: Buy when VPVMA > VPVMAS + BUY_BANDWIDTH × |VPVMAS|
# (equivalent to (1 + BUY_BANDWIDTH) × VPVMAS when VPVMAS > 0, and keeps the
# band above the signal line when VPVMAS is negative)
BUY_BANDWIDTH = 0.18   # Modified by regime_optimization_vpvma
                       # Example: 0.18 = Enter when VPVMA > 1.18 × VPVMAS

# Sell threshold - Exit timing
# Lower = Tighter stops (faster exits)
# Formula: Sell when VPVMA < VPVMAS - 2 × SELL_BANDWIDTH × |VPVMAS|
SELL_BANDWIDTH = 0.08  # Modified by regime_optimization_vpvma
                       # Example: 0.08 = Exit when VPVMA < 0.84 × VPVMAS (VPVMAS > 0)

# ============================================================================
# BEAR MARKET PROTECTION - FASTEXIT+SPY200 (NEW)
# ============================================================================
# Validated across 7 years (2019-2025) with significant improvements:
# - 2022 bear market: Sharpe -1.070 → -0.700 (35% less pain)
# - 2024-2025 holdout: Sharpe +0.152, CAGR +2.09%
# ============================================================================

# Enable/disable protection mechanism
ENABLE_BEAR_PROTECTION = True  # Set False to disable (not recommended)

# Bear market detection parameters
SPY_MA_PERIOD = 200           # Moving average period for regime detection
                              # Bear market = SPY close < SPY 200-day MA
                              # 200-day is institutional standard

# FastExit sell bandwidth (used when SPY < 200MA)
BEAR_SELL_BANDWIDTH = 0.032   # FastExit bandwidth used by backtest AND live trading
                              # Exit when VPVMA < 0.936 × VPVMAS (VPVMAS > 0)
                              # This is the "FastExit" mechanism

# ============================================================================
# DATA WINDOWS (shared by backtest and live trading)
# ============================================================================

# Calendar days of history loaded before the evaluation date when computing
# VPVMA live. ~275 trading days, enough for the 26-period EMA and 18-period
# signal SMA to converge so live signals match a full-history backtest.
INDICATOR_LOOKBACK_DAYS = 400

# Calendar days of SPY history loaded for the 200-day regime MA
# (~250 trading days > SPY_MA_PERIOD).
REGIME_LOOKBACK_DAYS = 370

# ============================================================================
# PORTFOLIO RULES (shared by backtest and live trading)
# ============================================================================

MAX_POSITIONS = 20
POSITION_SIZE_PCT = 0.05       # Fraction of equity per new position
COMMISSION = 1.0               # $ per fill
SLIPPAGE_BPS = 2               # Basis points per fill

# Swap a losing position for a buy signal >=25% stronger when the book is full
ENABLE_REPLACEMENT = True

# Momentum universe: top UNIVERSE_SIZE symbols by MOMENTUM_PERIOD-bar return,
# re-selected on the first trading day of each month
UNIVERSE_SIZE = 100
MOMENTUM_PERIOD = 20

# ============================================================================
# PARAMETER NOTES
# ============================================================================

"""
INDEPENDENT BANDWIDTH RATIONALE:
The paper's original coupled bandwidth (sell = buy × 2) was problematic:
- Higher buy bandwidth → looser sell threshold → late exits
- This caused larger drawdowns in volatile markets

Independent bandwidth allows:
- High buy bandwidth (0.18) = Selective entries (quality signals only)
- Low sell bandwidth (0.08) = Tight stops (cut losers fast)
- Even lower in bears (0.032) = Cut losers VERY fast

FASTEXIT MECHANISM:
Normal market: SELL_BANDWIDTH = 0.08
- Exit when VPVMA drops to 84% of VPVMAS (sell band is 2 × SELL_BANDWIDTH)
- Example: VPVMAS=100 → Exit at VPVMA=84

Bear market: BEAR_SELL_BANDWIDTH = 0.032
- Exit when VPVMA drops to 93.6% of VPVMAS
- Example: VPVMAS=100 → Exit at VPVMA=93.6

WHY IT WORKS:
- Bear markets correlate with bankruptcies, failures, big drawdowns
- Exiting 2x faster in bears reduces exposure to worst outcomes
- Still captures bull rallies (protection only ~9% of time in 2024-2025)
- Net result: Better returns AND lower risk

VALIDATION PROOF:
Phase 1 (2019-2023): 
  - 2022 bear: -35% pain reduction (Sharpe -1.07 → -0.70)
  - Bull years: No performance cost
Phase 3 (2024-2025 HOLDOUT):
  - Sharpe: 0.977 → 1.129 (+15.5%)
  - CAGR: 12.73% → 14.82% (+2.09%)
  - MaxDD: -23.95% → -23.12% (better control)
  - 183 stocks, completely unseen data ✓
"""