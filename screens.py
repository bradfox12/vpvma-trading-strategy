"""
Universe screens - which stocks the VPVMA strategy is allowed to trade

A screen runs on the first session of each SCREEN_FREQUENCY period (monthly or
quarterly) and returns up to SCREEN_SIZE symbols. The backtest and live trading
both build the screen's input with ScreenData, which only contains information
public on the screening date:

- prices/volumes for the last SCREEN_LOOKBACK_DAYS, up to the screening date
- the securities master (type, exchange, sector, listing dates)
- fundamentals whose available_date (filing date) is on or before the screening date

To add your own criteria: subclass Screen, list the fundamental fields you use
in `fields`, implement select(), and register it in SCREENS. Then set
config.SCREEN_NAME to its name. Field names depend on the fundamentals vendor.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

import config

LIQUIDITY_WINDOW = 60  # sessions for median dollar volume
MIN_HISTORY_BARS = 60


def rebalance_key(date, frequency: str = None) -> str:
    """Period label for a date: '2026-10' (monthly) or '2026Q4' (quarterly)"""
    frequency = frequency or config.SCREEN_FREQUENCY
    date = pd.Timestamp(date)
    if frequency == 'monthly':
        return f"{date:%Y-%m}"
    if frequency == 'quarterly':
        return f"{date.year}Q{date.quarter}"
    raise ValueError(f"Unknown SCREEN_FREQUENCY {frequency!r} (use 'monthly' or 'quarterly')")


@dataclass
class ScreenData:
    """Point-in-time inputs for one screening date"""
    asof: pd.Timestamp
    closes: pd.DataFrame                 # index: dates <= asof, columns: symbols
    volumes: pd.DataFrame
    securities: pd.DataFrame = field(default_factory=pd.DataFrame)
    fundamentals: pd.DataFrame = field(default_factory=pd.DataFrame)  # long rows, available_date <= asof

    @classmethod
    def from_panels(cls, asof, closes: pd.DataFrame, volumes: pd.DataFrame,
                    securities: pd.DataFrame = None, fundamentals: pd.DataFrame = None) -> 'ScreenData':
        """Slice full-history panels/rows down to what was known at `asof`"""
        asof = pd.Timestamp(asof)
        start = asof - pd.Timedelta(days=config.SCREEN_LOOKBACK_DAYS)
        window = (closes.index >= start) & (closes.index <= asof)
        c, v = closes.loc[window], volumes.loc[window]
        listed = c.columns[c.notna().any()]
        funds = fundamentals if fundamentals is not None else pd.DataFrame()
        if not funds.empty:
            funds = funds[funds['available_date'] <= asof]
        return cls(asof, c[listed], v[listed],
                   securities if securities is not None else pd.DataFrame(), funds)

    @classmethod
    def from_db(cls, db, asof, fields: List[str] = ()) -> 'ScreenData':
        """Live screening input from the database"""
        asof = pd.Timestamp(asof)
        bars = db.get_bars(asof - pd.Timedelta(days=config.SCREEN_LOOKBACK_DAYS), asof)
        closes = bars.pivot(index='timestamp', columns='symbol', values='close')
        volumes = bars.pivot(index='timestamp', columns='symbol', values='volume')
        # ~2.5 years of filings covers the 8 quarters growth/trend traits need
        funds = (db.get_fundamentals(asof, since=asof - pd.Timedelta(days=900), fields=list(fields))
                 if fields else pd.DataFrame())
        return cls(asof, closes, volumes, db.get_securities(), funds)

    def latest(self, fields: List[str], max_age_days: int = 450) -> pd.DataFrame:
        """
        Most recent available value per symbol for each field (index: symbol).
        Values whose period ended more than max_age_days ago are treated as missing.
        """
        f = self.fundamentals
        if f.empty:
            return pd.DataFrame(columns=fields, dtype=float)
        f = f[f['field'].isin(fields) & (f['period_end'] >= self.asof - pd.Timedelta(days=max_age_days))]
        f = f.sort_values(['period_end', 'available_date']).drop_duplicates(['symbol', 'field'], keep='last')
        return f.pivot(index='symbol', columns='field', values='value').reindex(columns=fields)

    def trailing_sum(self, field_name: str, periods: int = 4, max_span_days: int = None) -> pd.Series:
        """
        Sum of the last `periods` quarterly values (e.g. TTM revenue) per symbol.
        Symbols missing a quarter, or whose latest quarter is stale, are dropped.
        """
        max_span_days = max_span_days or periods * 115
        f = self.fundamentals
        if f.empty:
            return pd.Series(dtype=float)
        f = f[f['field'] == field_name].sort_values(['symbol', 'period_end', 'available_date'])
        f = f.drop_duplicates(['symbol', 'period_end'], keep='last').groupby('symbol').tail(periods)
        g = f.groupby('symbol')
        ok = (g['period_end'].count() == periods) & \
             ((g['period_end'].max() - g['period_end'].min()).dt.days <= max_span_days) & \
             (g['period_end'].max() >= self.asof - pd.Timedelta(days=200))
        return g['value'].sum()[ok]

    def liquidity(self) -> pd.DataFrame:
        """Per symbol: last_close, median_dollar_volume (last LIQUIDITY_WINDOW sessions), bars"""
        recent_c = self.closes.tail(LIQUIDITY_WINDOW)
        recent_v = self.volumes.tail(LIQUIDITY_WINDOW)
        last_close = self.closes.ffill().iloc[-1] if len(self.closes) else pd.Series(dtype=float)
        return pd.DataFrame({
            'last_close': last_close,
            'median_dollar_volume': (recent_c * recent_v).median(),
            'bars': self.closes.notna().sum(),
            'last_bar': self.closes.apply(pd.Series.last_valid_index),
        })


class Screen:
    """Base class: implement select() and list fundamental `fields` used"""
    name = 'base'
    fields: List[str] = []

    def eligible(self, data: ScreenData) -> pd.DataFrame:
        """
        Baseline filters every screen should apply: allowed security types,
        price, liquidity, enough history and a bar in the last week.
        Returns the liquidity table for the eligible symbols.
        """
        liq = data.liquidity()
        recent = data.asof - pd.Timedelta(days=7)
        ok = ((liq['last_close'] >= config.SCREEN_MIN_PRICE)
              & (liq['median_dollar_volume'] >= config.SCREEN_MIN_DOLLAR_VOLUME)
              & (liq['bars'] >= MIN_HISTORY_BARS)
              & (liq['last_bar'] >= recent))
        sec = data.securities
        if not sec.empty and config.SCREEN_SECURITY_TYPES:
            allowed = set(sec.loc[sec['type'].isin(config.SCREEN_SECURITY_TYPES), 'symbol'])
            ok &= liq.index.isin(allowed)
        ok &= liq.index != 'SPY'
        return liq[ok]

    def select(self, data: ScreenData) -> pd.DataFrame:
        """Return DataFrame [symbol, score] sorted best first (at most config.SCREEN_SIZE rows)"""
        raise NotImplementedError


class LiquidityScreen(Screen):
    """Placeholder: the most liquid eligible stocks by median dollar volume"""
    name = 'liquidity'

    def select(self, data: ScreenData) -> pd.DataFrame:
        liq = self.eligible(data)
        ranked = liq['median_dollar_volume'].sort_values(ascending=False).head(config.SCREEN_SIZE)
        return pd.DataFrame({'symbol': ranked.index, 'score': ranked.to_numpy()})


class ExampleFundamentalScreen(Screen):
    """
    TEMPLATE for a volume + fundamentals screen - copy and edit.

    Keeps liquid stocks with positive trailing-12-month revenue growth and
    positive TTM operating income, then ranks by dollar volume. The field names
    ('revenue', 'operating_income') must match what the fundamentals loader stores.
    """
    name = 'example_fundamental'
    fields = ['revenue', 'operating_income']

    def select(self, data: ScreenData) -> pd.DataFrame:
        liq = self.eligible(data)
        revenue_ttm = data.trailing_sum('revenue', 4)
        revenue_prior = data.trailing_sum('revenue', 8) - revenue_ttm
        op_income_ttm = data.trailing_sum('operating_income', 4)

        df = liq.join(pd.DataFrame({'rev': revenue_ttm, 'rev_prior': revenue_prior, 'oi': op_income_ttm}),
                      how='inner')
        df = df[(df['rev_prior'] > 0) & (df['rev'] > df['rev_prior']) & (df['oi'] > 0)]
        ranked = df['median_dollar_volume'].sort_values(ascending=False).head(config.SCREEN_SIZE)
        return pd.DataFrame({'symbol': ranked.index, 'score': ranked.to_numpy()})


class LeadersScreen(Screen):
    """
    Weighted factor score that looks for stocks resembling past big winners
    (see factor_model.py). Tradeable = 20-session average volume >=
    config.LEADERS_MIN_AVG_SHARES; keeps the top config.LEADERS_SIZE by score.
    Weights are learned from the factor history file, using only quarters whose
    12-month outcome was known on the screening date.
    """
    name = 'leaders'

    def __init__(self, history: Optional[pd.DataFrame] = None, name: str = 'leaders',
                 size_cap: Optional[float] = None, split: Optional[dict] = None):
        from factor_model import FUNDAMENTAL_FIELDS
        self.fields = FUNDAMENTAL_FIELDS
        self.name = name
        self.size_cap = size_cap          # None -> config.LEADERS_SIZE_WEIGHT_CAP
        self.split = split                # None -> config.LEADERS_SPLIT
        self._history = history

    @property
    def history(self) -> pd.DataFrame:
        if self._history is None:
            from factor_model import load_history
            self._history = load_history()
        return self._history

    def weights(self, asof) -> pd.Series:
        from factor_model import learn_weights
        return learn_weights(self.history, asof)

    def select(self, data: ScreenData) -> pd.DataFrame:
        from factor_model import compute_traits, select_universe, tradeable
        symbols = tradeable(data.closes, data.volumes, data.asof, data.securities)
        if len(symbols) == 0:
            return pd.DataFrame(columns=['symbol', 'score'])
        raw = compute_traits(data.closes, data.volumes, data.fundamentals, data.asof, symbols)
        ranked = select_universe(raw, self.history, data.asof, split=self.split, size_cap=self.size_cap)
        return pd.DataFrame({'symbol': ranked.index, 'score': ranked.to_numpy()})


class EligibleScreen(Screen):
    """Every stock passing the leaders volume and price rules, unscored (baseline)"""
    name = 'eligible'

    def select(self, data: ScreenData) -> pd.DataFrame:
        from factor_model import tradeable
        symbols = tradeable(data.closes, data.volumes, data.asof, data.securities)
        return pd.DataFrame({'symbol': list(symbols), 'score': 0.0})


SCREENS: Dict[str, Screen] = {s.name: s for s in (LiquidityScreen(), ExampleFundamentalScreen(),
                                                   LeadersScreen(), EligibleScreen())}


def get_screen(name: Optional[str] = None) -> Screen:
    name = name or config.SCREEN_NAME
    if name not in SCREENS:
        raise ValueError(f"Unknown screen {name!r}; available: {sorted(SCREENS)}")
    return SCREENS[name]
