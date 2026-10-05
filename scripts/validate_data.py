"""
Data quality checks for the OHLCV database

Run after the historical load and whenever results look odd:
    python scripts/validate_data.py

Checks (per symbol, against the SPY trading calendar):
- ERROR  SPY missing or shorter than the 200-day regime window
- ERROR  impossible bars: non-positive prices, low > open/close, high < open/close
- WARN   sessions missing inside the symbol's own date range (gaps)
- WARN   close-to-close moves beyond +100% / -50% (often an unadjusted split)
- WARN   last bar older than SPY's last bar (delisted, renamed or not updating)
- WARN   5+ consecutive zero-volume bars

Exit code 1 if any ERROR is found.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging

import numpy as np
import pandas as pd

import config
from logging_setup import setup_logging

logger = logging.getLogger('validate_data')

JUMP_UP, JUMP_DOWN = 1.0, -0.5
ZERO_VOLUME_RUN = 5


def _issue(issues, level, symbol, check, detail):
    issues.append({'level': level, 'symbol': symbol, 'check': check, 'detail': detail})


def validate(db) -> pd.DataFrame:
    """Return a DataFrame of issues [level, symbol, check, detail]"""
    issues = []
    spy = db.get_ohlcv_data('SPY')
    if len(spy) < config.SPY_MA_PERIOD:
        _issue(issues, 'ERROR', 'SPY', 'calendar', f"{len(spy)} bars - need at least {config.SPY_MA_PERIOD}")
        return pd.DataFrame(issues)
    calendar = pd.DatetimeIndex(spy['timestamp'])
    spy_last = calendar.max()

    for symbol in db.list_symbols():
        df = db.get_ohlcv_data(symbol)
        if df.empty:
            continue
        ts = pd.DatetimeIndex(df['timestamp'])

        if (ts != ts.normalize()).any():
            _issue(issues, 'WARN', symbol, 'timestamps', 'bars not stored at midnight (mixed sources?)')

        o, h, l, c = (df[k].to_numpy() for k in ('open', 'high', 'low', 'close'))
        bad = (np.minimum.reduce([o, h, l, c]) <= 0) | (l > np.minimum(o, c) * 1.0001) | (h < np.maximum(o, c) * 0.9999)
        if bad.any():
            dates = ', '.join(f"{d:%Y-%m-%d}" for d in ts[bad][:5])
            _issue(issues, 'ERROR', symbol, 'ohlc', f"{bad.sum()} impossible bars, e.g. {dates}")

        expected = calendar[(calendar >= ts.min()) & (calendar <= ts.max())]
        gaps = expected.difference(ts)
        if len(gaps):
            _issue(issues, 'WARN', symbol, 'gaps',
                   f"{len(gaps)} missing sessions, e.g. {', '.join(f'{d:%Y-%m-%d}' for d in gaps[:5])}")

        ret = pd.Series(c).pct_change()
        jumps = ret[(ret > JUMP_UP) | (ret < JUMP_DOWN)]
        if len(jumps):
            detail = ', '.join(f"{ts[i]:%Y-%m-%d} {ret[i]:+.0%}" for i in jumps.index[:5])
            _issue(issues, 'WARN', symbol, 'jump', f"{len(jumps)} extreme moves: {detail}")

        if ts.max() < spy_last:
            behind = len(calendar[calendar > ts.max()])
            _issue(issues, 'WARN', symbol, 'stale', f"last bar {ts.max():%Y-%m-%d} ({behind} sessions behind SPY)")

        zero = (df['volume'] == 0).astype(int)
        longest = zero.groupby((zero != zero.shift()).cumsum()).sum().max()
        if longest >= ZERO_VOLUME_RUN:
            _issue(issues, 'WARN', symbol, 'volume', f"{longest} consecutive zero-volume bars")

    return pd.DataFrame(issues, columns=['level', 'symbol', 'check', 'detail'])


def main():
    setup_logging('validate_data')
    from data.database import Database
    db = Database()

    ranges = db.symbol_ranges()
    logger.info("%d symbols, %d bars, %s to %s", len(ranges), ranges['bars'].sum(),
                ranges['first'].min().date() if len(ranges) else '-',
                ranges['last'].max().date() if len(ranges) else '-')

    issues = validate(db)
    for _, row in issues.iterrows():
        log = logger.error if row['level'] == 'ERROR' else logger.warning
        log("%-6s %-5s %-10s %s", row['symbol'], row['level'], row['check'], row['detail'])

    errors = (issues['level'] == 'ERROR').sum() if len(issues) else 0
    logger.info("Validation finished: %d errors, %d warnings", errors, len(issues) - errors)
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
