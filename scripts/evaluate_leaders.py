"""
Compare leaders-screen variants on the factor history (universe quality)

For every quarter, each variant selects its universe with the weights it would
have known then (factor_model.select_universe), and we measure what those
stocks did over the next 12 months versus every eligible stock (volume and
price rules). This judges the stock selection alone; backtest.py judges the
full strategy trading inside it.

Usage:
    python scripts/evaluate_leaders.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

import config
import factor_model as fm

VARIANTS = {
    '1_size_uncapped': {'size_cap': None, 'split': None},
    '2_size_cap_30pct': {'size_cap': 0.30, 'split': None},
    '3_split_150_core_100_emerging': {'size_cap': None,
                                      'split': {'core': 150, 'emerging': 100, 'emerging_max_value': 20e9}},
}
CHECK = ['AAPL', 'MSFT', 'NFLX', 'NVDA']


def evaluate(history: pd.DataFrame, size_cap, split) -> pd.DataFrame:
    rows, previous = [], None
    for date in sorted(history['date'].unique()):
        day = history[history['date'] == date].set_index('symbol')
        if config.LEADERS_MIN_PRICE:
            day = day[day['close'] >= config.LEADERS_MIN_PRICE]
        universe = fm.select_universe(day, history, date, split=split, size_cap=size_cap)
        chosen = day.loc[universe.index]
        rows.append({
            'date': date,
            'universe_median': chosen['fwd_return'].median(),
            'eligible_median': day['fwd_return'].median(),
            'universe_mean': chosen['fwd_return'].mean(),
            'eligible_mean': day['fwd_return'].mean(),
            'median_value_bn': np.exp(chosen['size']).median() / 1e9,
            'turnover': (len(set(universe.index) - previous) / len(universe)) if previous else np.nan,
            **{s: s in universe.index for s in CHECK},
        })
        previous = set(universe.index)
    return pd.DataFrame(rows)


def main():
    history = fm.load_history()
    summary = []
    for name, opts in VARIANTS.items():
        r = evaluate(history, **opts)
        done = r.dropna(subset=['universe_median'])
        summary.append({
            'variant': name,
            'median_12m_universe': done['universe_median'].median(),
            'median_12m_eligible': done['eligible_median'].median(),
            'mean_12m_universe': done['universe_mean'].mean(),
            'mean_12m_eligible': done['eligible_mean'].mean(),
            'quarters_better_pct': (done['universe_median'] > done['eligible_median']).mean() * 100,
            'typical_value_bn': r['median_value_bn'].median(),
            'quarterly_turnover_pct': r['turnover'].mean() * 100,
            **{f'{s}_in_pct': r[s].mean() * 100 for s in CHECK},
        })
        r.to_csv(Path(__file__).resolve().parent.parent / 'logs' / f'leaders_eval_{name}.csv', index=False)
    out = pd.DataFrame(summary).set_index('variant').T
    pd.set_option('display.width', 200)
    print(out.to_string(float_format=lambda v: f"{v:,.3f}" if abs(v) < 2 else f"{v:,.0f}"))
    return 0


if __name__ == '__main__':
    sys.exit(main())
