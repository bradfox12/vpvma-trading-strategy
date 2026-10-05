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

MAX_POSITIONS = 20             # Hold at most this many signals
POSITION_SIZE_PCT = 0.05       # Fraction of equity per new position
COMMISSION = 1.0               # $ per fill
SLIPPAGE_BPS = 2               # Basis points per fill

# Rank buffer for swaps. Each close, holdings and waiting buy candidates are
# ranked together by strength = (VPVMA - buy threshold) / |VPVMAS|.
# - A candidate qualifies while it ranks within MAX_POSITIONS (top 20) and is
#   still above its own buy threshold
# - It must qualify on SWAP_CONFIRM_DAYS consecutive closes (1 = no confirmation)
# - It then replaces the weakest holding ranked worse than SWAP_EXIT_RANK
#   (i.e. at least SWAP_EXIT_RANK signals are stronger than that holding)
SWAP_EXIT_RANK = 25
SWAP_CONFIRM_DAYS = 2
MAX_SWAPS_PER_DAY = None       # None = no cap

# ============================================================================
# UNIVERSE SCREEN (see screens.py)
# ============================================================================

SCREEN_NAME = 'liquidity'       # a key of screens.SCREENS - replace with your own screen
SCREEN_FREQUENCY = 'quarterly'  # 'monthly' or 'quarterly'; runs on the first session of the period
SCREEN_SIZE = 500               # Maximum tradable symbols (screens usually return fewer, ~250)
SCREEN_LOOKBACK_DAYS = 500      # Calendar days of prices available to the screen
                                # (12-month price strength + 250-session volume baseline)
SCREEN_MIN_PRICE = 5.0          # Exclude stocks below this close
SCREEN_MIN_DOLLAR_VOLUME = 5_000_000   # Minimum median daily $ volume (last 60 sessions)
SCREEN_SECURITY_TYPES = ['CS']  # Common stock only (needs the securities table)

# ============================================================================
# LEADERS SCREEN - weighted factor score (see factor_model.py)
# ============================================================================
# Tradeable: 20-session average volume >= LEADERS_MIN_AVG_SHARES. Each stock is
# scored on traits (growth, margins, price strength, accumulation, size...)
# ranked as percentiles; weights are learned from history: how strongly each
# trait separated "winners" (top LEADERS_WINNER_PCT of next-12-month return)
# from the rest, using only quarters whose outcome was known at the time.
LEADERS_MIN_AVG_SHARES = 250_000
LEADERS_AVG_VOLUME_DAYS = 20
LEADERS_SIZE = 250                       # stocks kept in the tradeable universe
LEADERS_HORIZON_DAYS = 365               # forward window that defines a winner
LEADERS_WINNER_PCT = 0.10                # top 10% = winner
# 'contribution': top 10% by dollars added to the market (market value x 12-month return)
# 'return':       top 10% by 12-month return
LEADERS_WINNER_DEFINITION = 'contribution'
LEADERS_SIZE_WEIGHT_CAP = None           # e.g. 0.30 limits the size trait to 30% of the weight
# Split universe: top 'core' by the full score, plus top 'emerging' among companies
# worth less than 'emerging_max_value', scored without size. None = one list.
LEADERS_SPLIT = None                     # e.g. {'core': 150, 'emerging': 100, 'emerging_max_value': 20e9}
LEADERS_HISTORY_START = '2012-01-01'     # first quarter used to learn weights
LEADERS_ZERO_NEGATIVE_WEIGHTS = True     # traits that marked losers get weight 0 (False = negative weight)
LEADERS_MIN_PRICE = 10.0                 # hard rule: last close must be at least $10
LEADERS_MISSING_PERCENTILE = 0.5         # score for a missing trait: 0.5 = neutral, 0.0 = lowest

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