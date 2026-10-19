"""
Follow-up to the event study: does VPVMA work as a trend FILTER, or only
inside strong-trend stocks?

Test 1 - state filter: on each day a stock is either ON or OFF:
    above     VPVMA above its signal line
    position  paper rules: ON from a buy signal until the next sell signal
  If the filter has an edge, ON stock-days earn more over the next 5/20
  sessions than OFF stock-days in the same group on the same dates.

Test 2 - strong-trend groups: buy/sell signal events and the state filter,
restricted to
    eligible   every tradeable stock (>= 250k shares 20-day average, >= $10)
    trend85    Gen 1 trend score >= 85, recomputed daily (MA20/50/200, 6-month
               return, average daily range)
    leaders    leaders universe (top 250, re-selected each quarter with weights
               known at the time)

Returns run from the next day's open. t-stats use non-overlapping dates (every
h-th session) so overlapping windows do not inflate them. 2023+ never loaded.

Usage:
    python scripts/signal_filter_study.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging

import numpy as np
import pandas as pd

import config
from logging_setup import setup_logging
from scripts.signal_event_study import (HOLDOUT_START, MIN_AVG_SHARES, MIN_PRICE, VARIANTS,
                                        forward_returns, load_panels, signals_for)

logger = logging.getLogger('signal_filter_study')
REPORT_DIR = Path(__file__).resolve().parent.parent / 'logs'
HORIZONS = [5, 20]
PERIODS = {'2012-2018 design': ('2012-01-01', '2018-12-31'),
           '2019-2022 validation': ('2019-01-01', '2022-12-31')}
STUDY_VARIANTS = ['paper_vpvma', 'macd_control']


def states_for(panels, name):
    """(buy, sell, above, position) boolean panels"""
    v = VARIANTS[name]
    close = panels['close']
    buy, sell = signals_for(panels, v)
    if v['kind'] == 'macd':
        c = close.ffill()
        macd = c.ewm(span=v['fast'], adjust=False).mean() - c.ewm(span=v['slow'], adjust=False).mean()
        above = (macd > macd.ewm(span=v['sign'], adjust=False).mean()) & close.notna()
    else:
        from main import calculate_vpvma_indicator
        saved = (config.WINDOW_FAST, config.WINDOW_SLOW, config.WINDOW_SIGN)
        config.WINDOW_FAST, config.WINDOW_SLOW, config.WINDOW_SIGN = v['fast'], v['slow'], v['sign']
        cols = {}
        try:
            for sym in close.columns:
                rows = close[sym].notna().to_numpy()
                if rows.sum() < v['slow'] + v['sign'] + 2:
                    continue
                r = calculate_vpvma_indicator(
                    panels['high'][sym].to_numpy()[rows], panels['low'][sym].to_numpy()[rows],
                    panels['close'][sym].to_numpy()[rows], panels['open'][sym].to_numpy()[rows],
                    panels['volume'][sym].to_numpy()[rows])
                s = pd.Series(False, index=close.index)
                s[close.index[rows]] = r['vpvma'] > r['vpvmas']
                cols[sym] = s
        finally:
            config.WINDOW_FAST, config.WINDOW_SLOW, config.WINDOW_SIGN = saved
        above = pd.DataFrame(cols).reindex(columns=close.columns, fill_value=False)
    marks = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    marks[buy] = 1.0
    marks[sell] = 0.0
    position = marks.ffill().fillna(0).astype(bool) & close.notna()
    return buy, sell, above, position


def trend85(panels):
    """Gen 1 monthly trend score >= 85, computed daily with data up to each day"""
    c, h, l = panels['close'], panels['high'], panels['low']
    ma20, ma50, ma200 = (c.rolling(n, min_periods=n).mean() for n in (20, 50, 200))
    ret6 = (c / c.shift(126) - 1) * 100
    atr = ((h - l).rolling(20, min_periods=20).mean() / c) * 100
    score = (20 * (c > ma200) + 15 * (ma50 > ma200) + 15 * (ma20 > ma50)
             + np.select([ret6 > 50, ret6 > 25, ret6 > 0], [30, 20, 10], 0)
             + np.select([atr >= 2.5, atr >= 1.5], [20, 10], 0))
    return (pd.DataFrame(score, index=c.index, columns=c.columns) >= 85) & ma200.notna()


def leaders_membership(index, columns):
    """Leaders universe per quarter (weights known at the time), held until the next quarter"""
    import factor_model as fm
    history = fm.load_history()
    member = pd.DataFrame(np.nan, index=index, columns=columns)
    for date in sorted(history['date'].unique()):
        if date >= HOLDOUT_START:
            break
        day = history[history['date'] == date].set_index('symbol')
        day = day[day['close'] >= config.LEADERS_MIN_PRICE]
        chosen = fm.select_universe(day, history, date, size_cap=0, split=None)
        if date in member.index:
            member.loc[date] = 0.0
            member.loc[date, member.columns.intersection(chosen.index)] = 1.0
    return member.ffill().fillna(0).astype(bool)


def t_stat(daily: pd.Series, h: int) -> float:
    s = daily.dropna().iloc[::h]
    return s.mean() / (s.std() / np.sqrt(len(s))) if len(s) > 2 and s.std() > 0 else np.nan


def main():
    setup_logging('signal_filter_study')
    from data.database import Database
    db = Database()
    start, end = pd.Timestamp('2012-01-01'), HOLDOUT_START - pd.Timedelta(days=1)
    panels = load_panels(db, start - pd.Timedelta(days=400), end + pd.Timedelta(days=60))
    idx, cols = panels['close'].index, panels['close'].columns

    vol20 = panels['volume'].rolling(20, min_periods=20).mean()
    eligible = (vol20 >= MIN_AVG_SHARES) & (panels['close'] >= MIN_PRICE)
    eligible.loc[(idx < start) | (idx > end)] = False
    groups = {'eligible': eligible,
              'trend85': eligible & trend85(panels),
              'leaders': eligible & leaders_membership(idx, cols)}
    for g, m in groups.items():
        logger.info("Group %s: %.0f stocks per day on average", g, m.sum(axis=1)[m.any(axis=1)].mean())

    fwd = {h: forward_returns(panels, h) for h in HORIZONS}
    rows = []
    for name in STUDY_VARIANTS:
        logger.info("Indicator states: %s", name)
        buy, sell, above, position = states_for(panels, name)
        for g, member in groups.items():
            for h in HORIZONS:
                r = fwd[h].where(member & fwd[h].notna())
                group_mean = r.mean(axis=1)
                elig_mean = fwd[h].where(eligible).mean(axis=1)
                for pname, (ps, pe) in PERIODS.items():
                    in_p = (idx >= ps) & (idx <= pe)
                    base = {'variant': name, 'group': g, 'horizon': h, 'period': pname}
                    gm = group_mean[in_p]
                    rows.append({**base, 'test': 'group vs random stock',
                                 'value_%': 100 * (gm - elig_mean[in_p]).mean(),
                                 't': t_stat(gm - elig_mean[in_p], h),
                                 'n': int(member[in_p].sum().sum())})
                    for sname, state in (('above', above), ('position', position)):
                        on = r.where(state).mean(axis=1)[in_p]
                        off = r.where(~state).mean(axis=1)[in_p]
                        share = (state & member)[in_p].sum().sum() / max(member[in_p].sum().sum(), 1)
                        rows.append({**base, 'test': f'state {sname}: ON minus OFF',
                                     'value_%': 100 * (on - off).mean(), 't': t_stat(on - off, h),
                                     'n': int((state & member)[in_p].sum().sum()), 'on_share_%': 100 * share})
                    for side, sig in (('BUY', buy), ('SELL', sell)):
                        ev = (r.where(sig) .sub(group_mean, axis=0))[in_p]
                        daily = ev.mean(axis=1)
                        rows.append({**base, 'test': f'{side} event vs group',
                                     'value_%': 100 * ev.stack().dropna().mean(), 't': t_stat(daily, h),
                                     'n': int(ev.notna().sum().sum())})
    out = pd.DataFrame(rows)
    REPORT_DIR.mkdir(exist_ok=True)
    out.to_csv(REPORT_DIR / 'signal_filter_study.csv', index=False)
    pd.set_option('display.width', 220)
    pd.set_option('display.max_rows', 500)
    print("\nvalue_% = average difference in forward return (percentage points). "
          "Positive is good for: group vs random, state ON minus OFF, BUY event. Negative is good for SELL.\n")
    print(out.set_index(['variant', 'group', 'test', 'horizon', 'period']).sort_index()
          .to_string(float_format=lambda x: f"{x:,.2f}"))
    return 0


if __name__ == '__main__':
    sys.exit(main())
