"""
Signal event study: do VPVMA signals predict returns at all?

For every buy and sell signal on a day the stock is tradeable (20-session
average volume >= 250k shares, close >= $10), measure the return from the NEXT
day's open to the close h sessions later, and compare it with the average
return of all tradeable stocks over the same dates (= entering a random
tradeable stock that day). This removes market moves, so what remains is what
the signal itself adds.

Variants:
  paper_vpvma      VPVMA 12/26/9, buy > 1.1x signal line, sell < 0.8x (paper Table 8),
                   sign-safe bands
  vpvma_crossover  VPVMA 12/26/9, plain crossover of the signal line
  macd_control     Standard MACD 12/26/9 on closes, plain crossover

The 2023+ holdout is never loaded.

Usage:
    python scripts/signal_event_study.py [--start 2012-01-01] [--end 2022-12-31]
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import logging

import numpy as np
import pandas as pd

import config
from logging_setup import setup_logging
from main import calculate_vpvma_indicator

logger = logging.getLogger('signal_event_study')
REPORT_DIR = Path(__file__).resolve().parent.parent / 'logs'
HOLDOUT_START = pd.Timestamp('2023-01-01')
HORIZONS = [5, 20, 60]
MIN_AVG_SHARES = 250_000
MIN_PRICE = 10.0

VARIANTS = {
    'paper_vpvma': {'kind': 'vpvma', 'fast': 12, 'slow': 26, 'sign': 9, 'buy_bw': 0.10, 'sell_bw': 0.10},
    'vpvma_crossover': {'kind': 'vpvma', 'fast': 12, 'slow': 26, 'sign': 9, 'buy_bw': 0.0, 'sell_bw': 0.0},
    'macd_control': {'kind': 'macd', 'fast': 12, 'slow': 26, 'sign': 9},
}


def load_panels(db, start, end):
    """open/high/low/close/volume panels (dates x symbols), chunked"""
    symbols = [s for s in db.list_symbols() if s != 'SPY']
    parts = {k: [] for k in ('open', 'high', 'low', 'close', 'volume')}
    for i in range(0, len(symbols), 300):
        bars = db.get_bars(start, end, symbols=symbols[i:i + 300],
                           columns=('open', 'high', 'low', 'close', 'volume'))
        for k in parts:
            parts[k].append(bars.pivot(index='timestamp', columns='symbol', values=k))
        logger.info("Loaded %d/%d symbols", min(i + 300, len(symbols)), len(symbols))
    return {k: pd.concat(v, axis=1).sort_index().rename_axis(index=None, columns=None) for k, v in parts.items()}


def signals_for(panels, v):
    """(buy, sell) boolean panels for one variant, computed per symbol on its own bars"""
    close = panels['close']
    buy = pd.DataFrame(False, index=close.index, columns=close.columns)
    sell = buy.copy()
    if v['kind'] == 'macd':
        c = close.ffill()
        macd = c.ewm(span=v['fast'], adjust=False).mean() - c.ewm(span=v['slow'], adjust=False).mean()
        sig = macd.ewm(span=v['sign'], adjust=False).mean()
        above = macd > sig
        valid = close.notna() & close.shift(1).notna() & (close.notna().cumsum() > v['slow'] + v['sign'])
        return (above & ~above.shift(1, fill_value=False) & valid,
                ~above & above.shift(1, fill_value=False) & valid)

    saved = (config.WINDOW_FAST, config.WINDOW_SLOW, config.WINDOW_SIGN, config.BUY_BANDWIDTH, config.SELL_BANDWIDTH)
    config.WINDOW_FAST, config.WINDOW_SLOW, config.WINDOW_SIGN = v['fast'], v['slow'], v['sign']
    config.BUY_BANDWIDTH, config.SELL_BANDWIDTH = v['buy_bw'], v['sell_bw']
    try:
        for j, sym in enumerate(close.columns):
            rows = close[sym].notna().to_numpy()
            if rows.sum() < v['slow'] + v['sign'] + 2:
                continue
            r = calculate_vpvma_indicator(
                panels['high'][sym].to_numpy()[rows], panels['low'][sym].to_numpy()[rows],
                panels['close'][sym].to_numpy()[rows], panels['open'][sym].to_numpy()[rows],
                panels['volume'][sym].to_numpy()[rows])
            idx = close.index[rows]
            buy.loc[idx, sym] = r['buy_signals']
            sell.loc[idx, sym] = r['sell_signals']
    finally:
        (config.WINDOW_FAST, config.WINDOW_SLOW, config.WINDOW_SIGN,
         config.BUY_BANDWIDTH, config.SELL_BANDWIDTH) = saved
    return buy, sell


def forward_returns(panels, h):
    """Next open -> close h sessions later; stocks that stop trading use their last close"""
    entry = panels['open'].shift(-1)
    exit_ = panels['close'].ffill(limit=h).shift(-h)
    return exit_ / entry - 1


def summarize(excess: pd.DataFrame, raw: pd.DataFrame, mask: pd.DataFrame, label: str) -> dict:
    ev = excess.where(mask).stack().dropna()   # pandas 3 keeps NaN cells when stacking
    rw = raw.where(mask).stack().dropna()
    by_date = ev.groupby(ev.index.get_level_values(0)).mean()
    t = by_date.mean() / (by_date.std() / np.sqrt(len(by_date))) if len(by_date) > 2 else np.nan
    return {'set': label, 'signals': len(ev), 'avg_return_%': 100 * rw.mean(),
            'avg_excess_%': 100 * ev.mean(), 'median_excess_%': 100 * ev.median(),
            'beat_random_%': 100 * (ev > 0).mean(), 't_stat': t}


def main():
    parser = argparse.ArgumentParser(description='VPVMA signal event study')
    parser.add_argument('--start', default='2012-01-01')
    parser.add_argument('--end', default='2022-12-31')
    args = parser.parse_args()
    start, end = pd.Timestamp(args.start), min(pd.Timestamp(args.end), HOLDOUT_START - pd.Timedelta(days=1))

    setup_logging('signal_event_study')
    from data.database import Database
    db = Database()
    # load 1 year before (indicator warm-up) and 100 days after (60-session forward window)
    panels = load_panels(db, start - pd.Timedelta(days=400), end + pd.Timedelta(days=100))
    idx = panels['close'].index
    in_period = (idx >= start) & (idx <= end)

    vol20 = panels['volume'].rolling(20, min_periods=20).mean()
    eligible = (vol20 >= MIN_AVG_SHARES) & (panels['close'] >= MIN_PRICE)
    eligible.loc[~in_period] = False
    periods = {'2012-2018 (design)': (idx >= '2012-01-01') & (idx <= '2018-12-31'),
               '2019-2022 (validation)': (idx >= '2019-01-01') & (idx <= '2022-12-31')}

    fwd = {h: forward_returns(panels, h) for h in HORIZONS}
    bench = {h: fwd[h].where(eligible).mean(axis=1) for h in HORIZONS}
    excess = {h: fwd[h].sub(bench[h], axis=0) for h in HORIZONS}

    rows = []
    for name, v in VARIANTS.items():
        logger.info("Computing signals: %s", name)
        buy, sell = signals_for(panels, v)
        for side, sig in (('BUY', buy), ('SELL', sell)):
            for h in HORIZONS:
                for pname, pmask in periods.items():
                    mask = sig & eligible & fwd[h].notna() & pd.DataFrame(
                        np.repeat(pmask[:, None], sig.shape[1], axis=1), index=sig.index, columns=sig.columns)
                    rows.append({'variant': name, 'side': side, 'horizon_days': h, 'period': pname,
                                 **summarize(excess[h], fwd[h], mask, pname)})
    out = pd.DataFrame(rows)
    REPORT_DIR.mkdir(exist_ok=True)
    out.to_csv(REPORT_DIR / 'signal_event_study.csv', index=False)

    base = {h: 100 * bench[h][eligible.any(axis=1)].mean() for h in HORIZONS}
    pd.set_option('display.width', 220)
    print(f"\nRandom tradeable stock, average forward return: "
          + ', '.join(f"{h}d {base[h]:.2f}%" for h in HORIZONS))
    print("\nExcess = signal's return minus the average tradeable stock over the same dates.")
    print("BUY signals should have positive excess, SELL signals negative. |t| > 2 is roughly significant.\n")
    show = out.drop(columns=['set']).set_index(['variant', 'side', 'horizon_days', 'period'])
    print(show.to_string(float_format=lambda x: f"{x:,.2f}"))
    return 0


if __name__ == '__main__':
    sys.exit(main())
