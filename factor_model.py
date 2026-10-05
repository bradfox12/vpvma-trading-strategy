"""
Leaders factor model - find stocks that look like the market's big winners did early on

At each quarterly rebalance:
1. Tradeable stocks: 20-session average volume >= LEADERS_MIN_AVG_SHARES.
2. Traits for each (point-in-time; fundamentals only once filed):
     rev_growth        trailing-12-month revenue vs the prior 12 months
     rev_accel         latest quarter's YoY growth minus YoY growth two quarters earlier
     gross_margin      trailing-12-month gross profit / revenue
     gross_margin_trend  gross margin vs a year earlier
     op_margin_trend   operating margin vs a year earlier
     earnings_growth   trailing-12-month net income vs the prior 12 months
     price_strength    12-month return excluding the latest month
     accumulation      volume on up days / volume on down days, last 60 sessions
     volume_growth     average volume last 60 sessions / the ~250 sessions before
     size              log market value (close x shares outstanding)
   Each trait is converted to a percentile among tradeable stocks (missing = 0.5).
3. Weights: for every PAST quarter whose 12-month outcome is already known,
   measure how much higher winners (top LEADERS_WINNER_PCT of forward return)
   ranked on each trait than everyone else; average over all such quarters
   since LEADERS_HISTORY_START. Traits that did not mark winners get weight 0
   (LEADERS_ZERO_NEGATIVE_WEIGHTS). Weights sum to 1.
4. Score = weighted sum of percentiles; the top LEADERS_SIZE form the universe.

The factor history (traits + forward returns per quarter) is built once by
scripts/build_factor_history.py and extended each quarter; the backtest and
live trading read the same file, so they use identical weights.
"""

import logging
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd

import config

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent
HISTORY_FILE = PROJECT_ROOT / 'data' / 'cache' / 'factor_history.csv.gz'

TRAITS = ['rev_growth', 'rev_accel', 'gross_margin', 'gross_margin_trend', 'op_margin_trend',
          'earnings_growth', 'price_strength', 'accumulation', 'volume_growth', 'size']
FUNDAMENTAL_FIELDS = ['revenue', 'cost_of_revenue', 'gross_profit', 'operating_income', 'net_income',
                      'shares_outstanding', 'net_interest_income', 'noninterest_income']
QUARTERS = 8


# ------------------------------------------------------------------ traits

def tradeable(closes: pd.DataFrame, volumes: pd.DataFrame, asof, securities: pd.DataFrame = None) -> pd.Index:
    """Symbols meeting the volume minimum, trading in the last week, common stock"""
    recent = volumes.loc[:asof].tail(config.LEADERS_AVG_VOLUME_DAYS)
    avg = recent.mean()
    last_bar = closes.loc[:asof].apply(pd.Series.last_valid_index)
    ok = (avg >= config.LEADERS_MIN_AVG_SHARES) & (last_bar >= pd.Timestamp(asof) - pd.Timedelta(days=7))
    if config.LEADERS_MIN_PRICE:
        ok &= closes.loc[:asof].ffill().iloc[-1].reindex(ok.index) >= config.LEADERS_MIN_PRICE
    if securities is not None and len(securities) and config.SCREEN_SECURITY_TYPES:
        allowed = set(securities.loc[securities['type'].isin(config.SCREEN_SECURITY_TYPES), 'symbol'])
        ok &= ok.index.isin(allowed)
    ok &= ok.index != 'SPY'
    return ok[ok].index


def quarterly_wide(fundamentals: pd.DataFrame, asof) -> dict:
    """
    {field: DataFrame index=symbol, columns 0..7 (0 = latest quarter)} using the
    latest version of each quarter public by `asof`. Rows whose 8 quarters are not
    consecutive (gaps) are kept per column; callers check spans via 'ends'.
    """
    f = fundamentals[(fundamentals['available_date'] <= asof) & fundamentals['field'].isin(FUNDAMENTAL_FIELDS)]
    f = f.sort_values('available_date').drop_duplicates(['symbol', 'field', 'period_end'], keep='last')
    f = f.sort_values('period_end')
    f['k'] = f.groupby(['symbol', 'field']).cumcount(ascending=False)
    f = f[f['k'] < QUARTERS]
    out = {}
    for field, g in f.groupby('field'):
        out[field] = g.pivot(index='symbol', columns='k', values='value').reindex(columns=range(QUARTERS))
        out[field + '_end'] = g.pivot(index='symbol', columns='k', values='period_end').reindex(columns=range(QUARTERS))
    return out


def _ttm(wide: pd.DataFrame, ends: pd.DataFrame, first: int, asof) -> pd.Series:
    """Sum of quarters first..first+3 if they are 4 consecutive quarters and recent enough"""
    cols = list(range(first, first + 4))
    span = (ends[cols[0]] - ends[cols[-1]]).dt.days
    recent = ends[0] >= pd.Timestamp(asof) - pd.Timedelta(days=200)
    ok = span.between(250, 300) & recent & wide[cols].notna().all(axis=1)
    if first:  # the earlier 12 months must directly precede the latest quarter's year
        lag = (ends[0] - ends[first]).dt.days
        ok &= lag.between(80 * first, 100 * first)
    return wide[cols].sum(axis=1).where(ok)


def compute_traits(closes: pd.DataFrame, volumes: pd.DataFrame, fundamentals: pd.DataFrame,
                   asof, symbols: pd.Index) -> pd.DataFrame:
    """Raw trait values for `symbols` as of `asof` (index symbol, columns TRAITS)"""
    asof = pd.Timestamp(asof)
    c = closes.loc[:asof, symbols].ffill()
    v = volumes.loc[:asof, symbols]
    traits = pd.DataFrame(index=symbols, columns=TRAITS, dtype=float)

    # --- price/volume
    if len(c) > 252:
        traits['price_strength'] = c.iloc[-22] / c.iloc[-253] - 1
    last60 = c.tail(61)
    up = last60.diff() > 0
    down = last60.diff() < 0
    v60 = v.tail(61)
    traits['accumulation'] = (v60.where(up).sum() / v60.where(down).sum().replace(0, np.nan))
    if len(v) > 310:
        traits['volume_growth'] = v.tail(60).mean() / v.iloc[-310:-60].mean().replace(0, np.nan)

    # --- fundamentals
    if fundamentals is None or fundamentals.empty:
        return traits
    q = quarterly_wide(fundamentals[fundamentals['symbol'].isin(symbols)], asof)
    empty = pd.DataFrame(index=symbols, columns=range(QUARTERS), dtype=float)
    empty_end = pd.DataFrame(pd.NaT, index=symbols, columns=range(QUARTERS)).astype('datetime64[ns]')

    def get(field):
        values = q.get(field, empty).reindex(symbols)
        ends = q.get(field + '_end', empty_end).reindex(symbols).astype('datetime64[ns]')
        return values, ends

    rev, rev_end = get('revenue')
    nii, nii_end = get('net_interest_income')
    nonii, _ = get('noninterest_income')
    bank_rev = nii + nonii.fillna(0)
    use_bank = rev.isna().all(axis=1) & bank_rev.notna().any(axis=1)
    rev, rev_end = rev.copy(), rev_end.copy()
    rev.loc[use_bank] = bank_rev.loc[use_bank]
    rev_end.loc[use_bank] = nii_end.loc[use_bank]

    gp, _ = get('gross_profit')
    cor, _ = get('cost_of_revenue')
    gp = gp.fillna(rev - cor)
    oi, _ = get('operating_income')
    ni, _ = get('net_income')

    rev0, rev1 = _ttm(rev, rev_end, 0, asof), _ttm(rev, rev_end, 4, asof)
    gp0, gp1 = _ttm(gp, rev_end, 0, asof), _ttm(gp, rev_end, 4, asof)
    oi0, oi1 = _ttm(oi, rev_end, 0, asof), _ttm(oi, rev_end, 4, asof)
    ni0, ni1 = _ttm(ni, rev_end, 0, asof), _ttm(ni, rev_end, 4, asof)

    traits['rev_growth'] = (rev0 / rev1.where(rev1 > 0) - 1)
    yoy0 = rev[0] / rev[4].where(rev[4] > 0) - 1
    yoy2 = rev[2] / rev[6].where(rev[6] > 0) - 1
    traits['rev_accel'] = (yoy0 - yoy2).where(rev0.notna() & rev1.notna())
    traits['gross_margin'] = gp0 / rev0.where(rev0 > 0)
    traits['gross_margin_trend'] = traits['gross_margin'] - gp1 / rev1.where(rev1 > 0)
    traits['op_margin_trend'] = oi0 / rev0.where(rev0 > 0) - oi1 / rev1.where(rev1 > 0)
    traits['earnings_growth'] = ((ni0 - ni1) / ni1.abs().where(ni1.abs() > 0)).clip(-5, 5)

    shares, shares_end = get('shares_outstanding')
    fresh = shares_end[0] >= asof - pd.Timedelta(days=400)
    mcap = (c.iloc[-1] * shares[0].where(fresh)) if len(c) else pd.Series(dtype=float)
    traits['size'] = np.log(mcap.where(mcap > 0))
    return traits.replace([np.inf, -np.inf], np.nan)


def percentiles(traits: pd.DataFrame) -> pd.DataFrame:
    """Cross-sectional percentile per trait (0..1); missing = LEADERS_MISSING_PERCENTILE"""
    return traits[TRAITS].rank(pct=True).fillna(config.LEADERS_MISSING_PERCENTILE)


# ----------------------------------------------------------------- history

def forward_returns(closes: pd.DataFrame, asof, symbols, horizon_days: int = None) -> pd.Series:
    """
    Return from the close on `asof` to the first close >= asof + horizon. Stocks that
    stopped trading earlier get their return to the last close (delistings count).
    NaN when the horizon has not ended yet.
    """
    horizon_days = horizon_days or config.LEADERS_HORIZON_DAYS
    asof = pd.Timestamp(asof)
    end = asof + pd.Timedelta(days=horizon_days)
    if closes.index.max() < end:
        return pd.Series(np.nan, index=symbols)
    start = closes.loc[:asof, symbols].ffill().iloc[-1]
    window = closes.loc[asof:end, symbols]
    finish = window.ffill().iloc[-1]
    return finish / start - 1


def build_history_rows(closes, volumes, securities, fundamentals, dates) -> pd.DataFrame:
    """
    Factor history rows [date, symbol, close, <raw traits>, fwd_return] for each date.
    Raw values (not percentiles) are stored, so the price minimum and the
    missing-value rule can be changed without rebuilding.
    """
    rows = []
    for date in dates:
        min_price = config.LEADERS_MIN_PRICE
        config.LEADERS_MIN_PRICE = None          # store every volume-qualified stock
        try:
            syms = tradeable(closes, volumes, date, securities)
        finally:
            config.LEADERS_MIN_PRICE = min_price
        if len(syms) == 0:
            continue
        raw = compute_traits(closes, volumes, fundamentals, date, syms)
        raw.insert(0, 'close', closes.loc[:date, syms].ffill().iloc[-1])
        raw['fwd_return'] = forward_returns(closes, date, syms)
        raw.insert(0, 'date', pd.Timestamp(date))
        rows.append(raw.rename_axis('symbol').reset_index())
        logger.info("Factor history %s: %d tradeable stocks", pd.Timestamp(date).date(), len(syms))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def history_percentiles(history: pd.DataFrame) -> pd.DataFrame:
    """
    Apply the current price minimum and turn raw traits into per-date percentiles
    (the same transformation the live screen applies on one date)
    """
    h = history
    if config.LEADERS_MIN_PRICE and 'close' in h:
        h = h[h['close'] >= config.LEADERS_MIN_PRICE]
    if config.LEADERS_WINNER_DEFINITION == 'contribution':
        h = h[h['size'].notna()]              # market value needed to measure contribution
    pct = h.groupby('date', group_keys=False)[TRAITS].apply(percentiles)
    out = pd.concat([h[['date', 'symbol', 'fwd_return']], pct], axis=1)
    out['size_raw'] = h['size']
    return out


def winner_metric(history: pd.DataFrame) -> pd.Series:
    """What makes a winner: 12-month return, or dollars added (market value x return)"""
    if config.LEADERS_WINNER_DEFINITION == 'contribution':
        return np.exp(history['size_raw']) * history['fwd_return']
    return history['fwd_return']


def label_winners(history: pd.DataFrame) -> pd.Series:
    """True for the top LEADERS_WINNER_PCT of the winner metric within each date"""
    metric = winner_metric(history)
    cutoff = metric.groupby(history['date']).transform(lambda r: r.quantile(1 - config.LEADERS_WINNER_PCT))
    return (metric >= cutoff) & metric.notna()


def trait_separation(history: pd.DataFrame) -> pd.DataFrame:
    """
    Per date: mean percentile of winners minus mean percentile of the rest, for each
    trait. `history` holds raw trait values (see history_percentiles).
    """
    h = history_percentiles(history)
    h = h[h['fwd_return'].notna()].copy()
    if h.empty:
        return pd.DataFrame(columns=TRAITS)
    h['winner'] = label_winners(h)
    win = h[h['winner']].groupby('date')[TRAITS].mean()
    rest = h[~h['winner']].groupby('date')[TRAITS].mean()
    return (win - rest).dropna(how='all')


def learn_weights(history: pd.DataFrame, asof, exclude=(), size_cap=None) -> pd.Series:
    """
    Trait weights for a rebalance on `asof`, from quarters since LEADERS_HISTORY_START
    whose forward window ended on or before `asof` (no look-ahead).

    Args:
        exclude: traits left out of the score (weight 0)
        size_cap: maximum weight for the size trait (default LEADERS_SIZE_WEIGHT_CAP);
                  the other weights are scaled up to fill the rest
    """
    size_cap = config.LEADERS_SIZE_WEIGHT_CAP if size_cap is None else size_cap
    asof = pd.Timestamp(asof)
    known = history[(history['date'] >= pd.Timestamp(config.LEADERS_HISTORY_START))
                    & (history['date'] + pd.Timedelta(days=config.LEADERS_HORIZON_DAYS) <= asof)]
    sep = trait_separation(known)
    if sep.empty:
        return pd.Series(1 / len(TRAITS), index=TRAITS)
    w = sep.mean().reindex(TRAITS).fillna(0)
    w[list(exclude)] = 0.0
    if config.LEADERS_ZERO_NEGATIVE_WEIGHTS:
        w = w.clip(lower=0)
    total = w.abs().sum()
    if total == 0:
        keep = [t for t in TRAITS if t not in exclude]
        return pd.Series({t: (1 / len(keep) if t in keep else 0.0) for t in TRAITS})
    w = w / total
    if size_cap and w['size'] > size_cap:
        others = w.drop('size')
        if others.abs().sum() > 0:
            w = pd.concat([others / others.abs().sum() * (1 - size_cap), pd.Series({'size': size_cap})]).reindex(TRAITS)
    return w


def score(pct: pd.DataFrame, weights: pd.Series) -> pd.Series:
    return pct[TRAITS].mul(weights.reindex(TRAITS).fillna(0), axis=1).sum(axis=1)


def select_universe(raw: pd.DataFrame, history: pd.DataFrame, asof, size: int = None,
                    split: dict = None, size_cap=None) -> pd.Series:
    """
    The tradeable universe for one date from raw trait values (index symbol).
    Used by the live screen, the backtest and the variant evaluation alike.

    Returns:
        Series symbol -> score, best first
    """
    size = size or config.LEADERS_SIZE
    split = config.LEADERS_SPLIT if split is None else split
    pct = percentiles(raw)
    full = score(pct, learn_weights(history, asof, size_cap=size_cap)).sort_values(ascending=False)
    if not split:
        return full.head(size)
    core = full.head(split['core'])
    value = np.exp(raw['size'])
    pool = raw.index[(value < split['emerging_max_value']) & ~raw.index.isin(core.index)]
    if len(pool) == 0:
        return core
    emerging_pct = percentiles(raw.loc[pool])
    emerging = score(emerging_pct, learn_weights(history, asof, exclude=('size',))) \
        .sort_values(ascending=False).head(split['emerging'])
    # emerging scores are on their own scale; list them after the core
    return pd.concat([core, emerging - emerging.max() + core.min() - 1e-9])


# ----------------------------------------------------------- history file

def load_history(path: Path = None) -> pd.DataFrame:
    path = path or HISTORY_FILE
    if not path.exists():
        return pd.DataFrame(columns=['date', 'symbol'] + TRAITS + ['fwd_return'])
    return pd.read_csv(path, parse_dates=['date'])


def save_history(history: pd.DataFrame, path: Path = None):
    path = path or HISTORY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp.gz')
    history.sort_values(['date', 'symbol']).to_csv(tmp, index=False, compression='gzip')
    tmp.replace(path)
