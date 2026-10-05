"""
Backtest VPVMA inside several universe screens over the same period

Loads prices once, runs each screen at every quarterly rebalance (weights known
at the time only), then simulates the strategy in each universe.

Usage:
    python scripts/compare_universes.py [--start 2014-01-02] [--end YYYY-MM-DD]
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import logging
from datetime import timedelta

import pandas as pd

import config
from logging_setup import setup_logging
from backtest import load_close_volume_panels, load_frames, rebalance_dates, run_screens, simulate
from screens import EligibleScreen, LeadersScreen

logger = logging.getLogger('compare_universes')
REPORT_DIR = Path(__file__).resolve().parent.parent / 'logs'


def screens():
    return {
        'eligible_all': EligibleScreen(),
        '1_size_uncapped': LeadersScreen(name='leaders_uncapped', size_cap=0),
        '2_size_cap_30pct': LeadersScreen(name='leaders_cap30', size_cap=0.30),
        '3_split_150_100': LeadersScreen(name='leaders_split', size_cap=0,
                                         split={'core': 150, 'emerging': 100, 'emerging_max_value': 20e9}),
    }


def main():
    parser = argparse.ArgumentParser(description='Backtest VPVMA in several universes')
    parser.add_argument('--start', default='2014-01-02')
    parser.add_argument('--end')
    args = parser.parse_args()

    setup_logging('compare_universes')
    from data.database import Database
    db = Database()
    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end) if args.end else db.latest_timestamp('SPY')

    spy = db.get_ohlcv_data('SPY', start_date=start - timedelta(days=config.REGIME_LOOKBACK_DAYS), end_date=end)
    days = pd.DatetimeIndex(spy['timestamp'])
    dates = rebalance_dates(days[(days >= start) & (days <= end)])
    symbols = [s for s in db.list_symbols() if s != 'SPY']
    closes, volumes = load_close_volume_panels(db, symbols, start - timedelta(days=config.SCREEN_LOOKBACK_DAYS), end)
    securities = db.get_securities()
    fields = LeadersScreen().fields
    fundamentals = db.get_fundamentals(end, fields=fields)

    universes = {}
    for name, screen in screens().items():
        universes[name] = run_screens(screen, dates, closes, volumes, securities, fundamentals)
    del closes, volumes

    needed = sorted(set().union(*(set(h['symbols']) for hist in universes.values() for h in hist)))
    frames = load_frames(db, needed, start, end)

    rows = []
    for name, history in universes.items():
        logger.info("Simulating %s", name)
        res = simulate({s: f for s, f in frames.items() if any(s in h['symbols'] for h in history)},
                       spy, start, end, 100_000, history)
        m = res['metrics']
        res['history'][['date', 'equity']].to_csv(REPORT_DIR / f'equity_{name}.csv', index=False)
        rows.append({'universe': name,
                     'avg_universe_size': sum(len(h['symbols']) for h in history) / len(history),
                     **{k: m[k] for k in ('total_return', 'cagr', 'sharpe', 'sortino', 'max_dd', 'annual_vol',
                                          'win_rate', 'profit_factor', 'num_round_trips', 'avg_hold_days')}})
    spy_curve = spy.set_index('timestamp')['close'].loc[start:end]
    years = (spy_curve.index[-1] - spy_curve.index[0]).days / 365.25
    rows.append({'universe': 'SPY buy & hold', 'total_return': (spy_curve.iloc[-1] / spy_curve.iloc[0] - 1) * 100,
                 'cagr': ((spy_curve.iloc[-1] / spy_curve.iloc[0]) ** (1 / years) - 1) * 100,
                 'max_dd': (spy_curve / spy_curve.cummax() - 1).min() * 100})
    out = pd.DataFrame(rows).set_index('universe')
    out.to_csv(REPORT_DIR / 'compare_universes.csv')
    pd.set_option('display.width', 220)
    print(f"\nVPVMA backtest {start.date()} to {end.date()}, $100,000, rank-buffer swaps, next-open fills\n")
    print(out.T.to_string(float_format=lambda v: f"{v:,.2f}"))
    return 0


if __name__ == '__main__':
    sys.exit(main())
