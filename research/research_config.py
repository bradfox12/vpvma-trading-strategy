"""
Research Framework Configuration
================================
Configuration for universe optimization research
"""

from datetime import datetime
from pathlib import Path

# ============================================================================
# WALK-FORWARD WINDOWS
# ============================================================================

WALK_FORWARD_WINDOWS = [
    {
        'name': 'window_1_2018_2019',
        'train_start': '2018-01-01',
        'train_end': '2019-12-31',
        'description': 'Pre-COVID period'
    },
    {
        'name': 'window_2_2019_2020',
        'train_start': '2019-01-01',
        'train_end': '2020-12-31',
        'description': 'COVID crash + recovery'
    },
    {
        'name': 'window_3_2020_2021',
        'train_start': '2020-01-01',
        'train_end': '2021-12-31',
        'description': 'Recovery + inflation concerns'
    },
    {
        'name': 'window_4_2021_2022',
        'train_start': '2021-01-01',
        'train_end': '2022-12-31',
        'description': 'Fed tightening + bear market'
    },
    {
        'name': 'window_5_2022_2023',
        'train_start': '2022-01-01',
        'train_end': '2023-12-31',
        'description': 'Bear bottom + 2023 rally'
    }
]

# Validation period (out-of-sample holdout)
VALIDATION_PERIOD = {
    'name': 'validation_2024_2025',
    'start': '2024-01-01',
    'end': '2025-11-26',
    'description': '2024-2025 bull market (completely unseen)'
}

# ============================================================================
# METRICS TO TEST
# ============================================================================

METRICS = {
    # Tier 1: Trend Quality (Most Robust)
    'adx': {
        'name': 'ADX',
        'description': 'Average Directional Index - trend strength',
        'module': 'research.metrics.adx',
        'function': 'calculate_adx',
        'higher_is_better': True,
        'threshold': 25,  # ADX > 25 = strong trend
        'tier': 1
    },
    'ma_alignment': {
        'name': 'MA Alignment Score',
        'description': 'Moving average trend cleanliness (0-3)',
        'module': 'research.metrics.ma_alignment',
        'function': 'calculate_ma_alignment',
        'higher_is_better': True,
        'threshold': 2,  # Score >= 2 = good trend
        'tier': 1
    },
    'momentum_20': {
        'name': '20-Day Momentum',
        'description': 'Price momentum over 20 days',
        'module': 'research.metrics.momentum',
        'function': 'calculate_momentum',
        'higher_is_better': True,
        'threshold': 0.05,  # > 5% positive momentum
        'tier': 1
    },
    
    # Tier 2: Conviction
    'relative_strength': {
        'name': 'Relative Strength vs SPY',
        'description': 'Outperformance vs market',
        'module': 'research.metrics.relative_strength',
        'function': 'calculate_relative_strength',
        'higher_is_better': True,
        'threshold': 1.1,  # 10% outperformance
        'tier': 2
    },
    'volume_weighted_momentum': {
        'name': 'Volume-Weighted Momentum',
        'description': 'Momentum × volume ratio',
        'module': 'research.metrics.volume_weighted',
        'function': 'calculate_volume_weighted_momentum',
        'higher_is_better': True,
        'threshold': 0.05,
        'tier': 2
    },
    'up_day_volume_ratio': {
        'name': 'Up-Day Volume Ratio',
        'description': 'Buying vs selling pressure',
        'module': 'research.metrics.volume_ratio',
        'function': 'calculate_up_day_volume_ratio',
        'higher_is_better': True,
        'threshold': 1.3,  # 30% more volume on up days
        'tier': 2
    },
    
    # Tier 3: Volatility Quality
    'upside_downside_vol': {
        'name': 'Upside/Downside Vol Ratio',
        'description': 'Healthy vs bearish volatility',
        'module': 'research.metrics.volatility_ratio',
        'function': 'calculate_upside_downside_ratio',
        'higher_is_better': True,
        'threshold': 1.0,  # Bigger up moves than down
        'tier': 3
    },
    'atr_trend': {
        'name': 'ATR Trend',
        'description': 'Volatility expansion/contraction',
        'module': 'research.metrics.atr_trend',
        'function': 'calculate_atr_trend',
        'higher_is_better': True,
        'threshold': 1.0,  # Expanding volatility
        'tier': 3
    }
}

# ============================================================================
# UNIVERSE SIZES TO TEST
# ============================================================================

UNIVERSE_SIZES = [50, 100, 150, 200]

# Also test current static universe size for comparison
TEST_STATIC_BASELINE = True

# ============================================================================
# PATHS
# ============================================================================

# Base paths
PROJECT_ROOT = Path(__file__).parent.parent
RESEARCH_ROOT = PROJECT_ROOT / 'research'
RESULTS_ROOT = RESEARCH_ROOT / 'results'

# Result subdirectories
METRICS_DIR = RESULTS_ROOT / 'metrics'
BACKTESTS_DIR = RESULTS_ROOT / 'backtests'
AGGREGATED_DIR = RESULTS_ROOT / 'aggregated'
REPORTS_DIR = RESULTS_ROOT / 'reports'

# Create directories if they don't exist
for dir_path in [METRICS_DIR, BACKTESTS_DIR, AGGREGATED_DIR, REPORTS_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)

# ============================================================================
# DATABASE
# ============================================================================

DB_TYPE = 'postgresql'

# Metric calculation settings
METRIC_CALC_SETTINGS = {
    'lookback_days': 365,  # Need 1 year of history for some metrics
    'min_data_points': 200,  # Minimum bars required per stock
    'batch_size': 50,  # Process 50 stocks at a time
}

# ============================================================================
# BACKTEST SETTINGS
# ============================================================================

# Use existing VPVMA parameters from config.py
# BUY_BANDWIDTH = 0.18
# SELL_BANDWIDTH = 0.08
# WINDOW_SIGN = 18
# WINDOW_FAST = 12
# WINDOW_SLOW = 26

# Portfolio settings
INITIAL_CAPITAL = 100000
MAX_POSITIONS = 20
COMMISSION = 1
SLIPPAGE_BPS = 2

# ============================================================================
# FILTERING CRITERIA
# ============================================================================

# Minimum requirements for stock inclusion
MIN_REQUIREMENTS = {
    'min_price': 5.0,  # Avoid penny stocks
    'min_avg_volume': 500_000,  # 500K shares/day minimum
    'min_dollar_volume': 5_000_000,  # $5M/day minimum
    'max_price': 5000,  # Exclude ultra-high price stocks (BRK.A, etc.)
}

# ============================================================================
# PERFORMANCE TARGETS
# ============================================================================

# Baseline (from your validated 2024-2025 holdout)
BASELINE_METRICS = {
    'sharpe': 0.977,
    'cagr': 12.73,
    'win_rate': 56.0,
    'max_drawdown': -23.95
}

# Improvement targets
TARGET_METRICS = {
    'sharpe': 1.10,  # +13% improvement
    'cagr': 14.0,    # +10% improvement
    'win_rate': 58.0,  # +2% improvement
    'max_drawdown': -23.0  # Better control
}

# ============================================================================
# REPORTING
# ============================================================================

# What to include in reports
REPORT_SETTINGS = {
    'include_plots': True,
    'plot_format': 'png',
    'plot_dpi': 300,
    'include_trade_list': False,  # Too large for reports
    'top_n_configs': 10,  # Show top 10 configurations
    'generate_html': True,
    'generate_pdf': False,  # Set True if you have wkhtmltopdf
}

# ============================================================================
# COMPUTATIONAL SETTINGS
# ============================================================================

# Multiprocessing
USE_MULTIPROCESSING = True
MAX_WORKERS = 4  # Adjust based on your CPU

# Caching
CACHE_METRICS = True  # Save calculated metrics to avoid recomputation
CACHE_BACKTESTS = True  # Save backtest results

# Logging
LOG_LEVEL = 'INFO'  # DEBUG, INFO, WARNING, ERROR
LOG_FILE = RESULTS_ROOT / 'research.log'

# ============================================================================
# VALIDATION
# ============================================================================

# Minimum windows that must show improvement
MIN_SUCCESSFUL_WINDOWS = 3  # At least 3 out of 5 windows must beat baseline

# Statistical significance
SIGNIFICANCE_LEVEL = 0.05  # For t-tests comparing metrics

print(f"✅ Research configuration loaded")
print(f"   Walk-forward windows: {len(WALK_FORWARD_WINDOWS)}")
print(f"   Metrics to test: {len(METRICS)}")
print(f"   Universe sizes: {UNIVERSE_SIZES}")
print(f"   Results will be saved to: {RESULTS_ROOT}")