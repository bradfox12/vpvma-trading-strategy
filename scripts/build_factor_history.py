"""
Build / extend the leaders factor history and report what the data says

For the first session of every quarter since LEADERS_HISTORY_START: trait
percentiles of every tradeable stock plus its next-12-month return. The file
(data/cache/factor_history.csv.gz) is what the leaders screen learns its
weights from, in the backtest and in live trading.

Rerunning only adds new quarters and fills in 12-month returns that have
completed since (daily_update.py calls update_history() for you).

Usage:
    python scripts/build_factor_history.py            # build/extend + report
    python scripts/build_factor_history.py --rebuild  # recompute everything
    python scripts/build_factor_history.py --report   # report only
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import logging

import pandas as pd

import config
from logging_setup import setup_logging
import factor_model as fm

logger = logging.getLogger('build_factor_history')
REPORT_DIR = Path(__file__).resolve().parent.parent / 'logs'
CHECK_SYMBOLS = ['AAPL', 'MSFT', 'NFLX', 'NVDA']


def quarter_starts(db, start) -> list:
    """First SPY session of each quarter from `start`"""
    spy = db.get_ohlcv_data('SPY', start_date=start)
    days = pd.DatetimeIndex(spy['timestamp'])
    keys = days.to_period('Q')
    return [d for i, d in enumerate(days) if i == 0 or keys[i] != keys[i - 1]]


def update_history(db, rebuild: bool = False) -> pd.DataFrame:
    """Add missing quarters and fill completed forward returns; returns the history"""
    from backtest import load_close_volume_panels

    history = fm.load_history() if not rebuild else fm.load_history(Path('/nonexistent'))
    dates = quarter_starts(db, config.LEADERS_HISTORY_START)
    have = set(history['date']) if len(history) else set()
    missing = [d for d in dates if d not in have]
    pending = history[history['fwd_return'].isna()]['date'].unique() if len(history) else []
    horizon_done = [d for d in pending
                    if d + pd.Timedelta(days=config.LEADERS_HORIZON_DAYS) <= db.latest_timestamp('SPY')]
    if not missing and not horizon_done:
        logger.info("Factor history up to date (%d quarters)", len(have))
        return history

    first = min(missing + list(horizon_done))
    load_from = first - pd.Timedelta(days=config.SCREEN_LOOKBACK_DAYS + 30)
    symbols = [s for s in db.list_symbols() if s != 'SPY']
    logger.info("Loading prices for %d symbols from %s...", len(symbols), load_from.date())
    closes, volumes = load_close_volume_panels(db, symbols, load_from, db.latest_timestamp('SPY'))
    securities = db.get_securities()
    fundamentals = db.get_fundamentals('2100-01-01', since=first - pd.Timedelta(days=900),
                                       fields=fm.FUNDAMENTAL_FIELDS)

    if missing:
        new_rows = fm.build_history_rows(closes, volumes, securities, fundamentals, missing)
        history = pd.concat([history, new_rows], ignore_index=True) if len(history) else new_rows
    for d in horizon_done:
        rows = history['date'] == d
        history.loc[rows, 'fwd_return'] = fm.forward_returns(
            closes, d, history.loc[rows, 'symbol']).to_numpy()
    fm.save_history(history)
    logger.info("Factor history: %d quarters, %d rows (%d added, %d returns completed)",
                history['date'].nunique(), len(history), len(missing), len(horizon_done))
    return history


def report(history: pd.DataFrame):
    pd.set_option('display.width', 200)
    sep = fm.trait_separation(history[history['date'] >= pd.Timestamp(config.LEADERS_HISTORY_START)])
    if sep.empty:
        logger.info("No completed 12-month outcomes yet")
        return
    summary = pd.DataFrame({
        'avg_separation': sep.mean(),
        'quarters_positive_pct': (sep > 0).mean() * 100,
        'weight_now': fm.learn_weights(history, pd.Timestamp.now()),
    }).sort_values('avg_separation', ascending=False)
    REPORT_DIR.mkdir(exist_ok=True)
    summary.to_csv(REPORT_DIR / 'leaders_trait_summary.csv')
    sep.to_csv(REPORT_DIR / 'leaders_trait_separation_by_quarter.csv')
    print("\n=== TRAITS: how much higher winners ranked (percentile points, avg over "
          f"{len(sep)} quarters) ===")
    print(summary.to_string(float_format=lambda v: f"{v:,.3f}"))

    # weights over time (as the backtest would have used them)
    dates = sorted(history['date'].unique())
    over_time = pd.DataFrame({d: fm.learn_weights(history, d) for d in dates[4::4]}).T
    over_time.to_csv(REPORT_DIR / 'leaders_weights_over_time.csv')
    print("\n=== WEIGHTS USED AT EACH YEAR'S FIRST REBALANCE ===")
    print(over_time.to_string(float_format=lambda v: f"{v:.2f}"))

    # sanity check: where did the market leaders rank, using weights known at the time?
    rows = []
    pct_all = fm.history_percentiles(history)
    for d in dates:
        h = pct_all[pct_all['date'] == d]
        s = fm.score(h.set_index('symbol'), fm.learn_weights(history, d))
        rank = s.rank(ascending=False)
        for sym in CHECK_SYMBOLS:
            if sym in rank.index:
                rows.append({'date': d.date(), 'symbol': sym, 'rank': int(rank[sym]), 'of': len(rank),
                             'in_top_250': rank[sym] <= config.LEADERS_SIZE,
                             'next_12m_return': h.set_index('symbol').at[sym, 'fwd_return']})
    check = pd.DataFrame(rows)
    check.to_csv(REPORT_DIR / 'leaders_check_symbols.csv', index=False)
    print(f"\n=== {', '.join(CHECK_SYMBOLS)}: share of quarters in the top {config.LEADERS_SIZE} ===")
    print(check.groupby('symbol')['in_top_250'].mean().map(lambda v: f"{v:.0%}").to_string())
    print(f"\nDetails in {REPORT_DIR}: leaders_trait_summary.csv, leaders_weights_over_time.csv, "
          "leaders_check_symbols.csv")


def main():
    parser = argparse.ArgumentParser(description='Build/extend the leaders factor history')
    parser.add_argument('--rebuild', action='store_true')
    parser.add_argument('--report', action='store_true', help='Only print the report')
    args = parser.parse_args()

    setup_logging('build_factor_history')
    history = fm.load_history()
    if not args.report:
        from data.database import Database
        history = update_history(Database(), rebuild=args.rebuild)
    report(history)
    return 0


if __name__ == '__main__':
    sys.exit(main())
