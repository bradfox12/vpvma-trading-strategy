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
# METRICS TO TEST (implemented in research/*_metric.py)
# ============================================================================

METRICS = {
    'adx_14': 'ADX(14) - trend strength',
    'ma_alignment_20_50_200': 'MA alignment score (0-3) - trend quality',
    'momentum_20d': '20-day price momentum',
}

# ============================================================================
# UNIVERSE SIZES TO TEST
# ============================================================================

UNIVERSE_SIZES = [50, 100, 150, 200]

# ============================================================================
# PATHS
# ============================================================================

PROJECT_ROOT = Path(__file__).parent.parent
RESULTS_ROOT = PROJECT_ROOT / 'research' / 'results'
METRICS_DIR = RESULTS_ROOT / 'metrics'
BACKTESTS_DIR = RESULTS_ROOT / 'backtests'

for dir_path in [METRICS_DIR, BACKTESTS_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)

# ============================================================================
# BACKTEST / SELECTION SETTINGS
# ============================================================================

# Portfolio rules (positions, sizing, costs) come from config.py
INITIAL_CAPITAL = 100000

# A configuration must complete in every walk-forward window to be eligible,
# and is ranked by its MEAN Sharpe across windows. Only the single top-ranked
# configuration is evaluated on the holdout unless --validate-top is raised.
SELECTION_STAT = 'mean'

# Minimum requirements for stock inclusion
MIN_REQUIREMENTS = {
    'min_price': 5.0,  # Avoid penny stocks
    'min_avg_volume': 500_000,  # 500K shares/day minimum
    'min_dollar_volume': 5_000_000,  # $5M/day minimum
    'max_price': 5000,  # Exclude ultra-high price stocks (BRK.A, etc.)
}

# Reference result to compare against. These are PRE-FIX numbers (before the
# data adjustment and signal fixes); replace them with a fresh
# `python backtest.py` run over VALIDATION_PERIOD before drawing conclusions.
BASELINE_METRICS = {
    'sharpe': 0.977,
    'cagr': 12.73,
    'win_rate': 56.0,
    'max_drawdown': -23.95
}
