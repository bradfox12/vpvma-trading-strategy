import pandas as pd
import pytest

import config
from screens import ExampleFundamentalScreen, LiquidityScreen, ScreenData, rebalance_key
from tests.conftest import make_ohlcv


def panels(symbols, start='2019-01-01', end='2020-06-30', price=None):
    dates = pd.bdate_range(start, end)
    closes, volumes = {}, {}
    for i, s in enumerate(symbols):
        df = make_ohlcv(dates, i)
        closes[s] = df.set_index('timestamp')['close'] * (price[s] / 100 if price and s in price else 1)
        volumes[s] = df.set_index('timestamp')['volume']
    return pd.DataFrame(closes), pd.DataFrame(volumes)


def quarters(symbol, field, values, first_period='2018-03-31', lag_days=40):
    periods = pd.date_range(first_period, periods=len(values), freq='QE')
    return pd.DataFrame({'symbol': symbol, 'field': field, 'period_end': periods,
                         'available_date': periods + pd.Timedelta(days=lag_days), 'value': values})


def test_rebalance_key():
    assert rebalance_key('2026-11-15', 'quarterly') == '2026Q4'
    assert rebalance_key('2026-11-15', 'monthly') == '2026-11'


def test_fundamentals_are_point_in_time():
    closes, volumes = panels(['AAA'])
    funds = quarters('AAA', 'revenue', [1, 2, 3, 4, 5, 6, 7, 8, 9])  # last period 2020-03-31, public 2020-05-10
    before = ScreenData.from_panels('2020-05-01', closes, volumes, fundamentals=funds)
    after = ScreenData.from_panels('2020-05-15', closes, volumes, fundamentals=funds)
    assert before.latest(['revenue']).loc['AAA', 'revenue'] == 8
    assert after.latest(['revenue']).loc['AAA', 'revenue'] == 9
    assert after.trailing_sum('revenue', 4)['AAA'] == 6 + 7 + 8 + 9
    assert before.closes.index.max() <= pd.Timestamp('2020-05-01')


def test_eligible_applies_type_price_and_liquidity(monkeypatch):
    monkeypatch.setattr(config, 'SCREEN_SECURITY_TYPES', ['CS'])
    closes, volumes = panels(['CS1', 'ETF1', 'PENNY', 'SPY'], price={'PENNY': 1})
    securities = pd.DataFrame({'symbol': ['CS1', 'ETF1', 'PENNY', 'SPY'], 'type': ['CS', 'ETF', 'CS', 'ETF']})
    data = ScreenData.from_panels('2020-06-30', closes, volumes, securities=securities)
    assert LiquidityScreen().select(data)['symbol'].tolist() == ['CS1']


def test_example_fundamental_screen_filters_on_growth():
    closes, volumes = panels(['GROW', 'SHRINK', 'NOFUND'])
    funds = pd.concat([
        quarters('GROW', 'revenue', [10] * 4 + [12] * 4 + [15]),
        quarters('GROW', 'operating_income', [1] * 9),
        quarters('SHRINK', 'revenue', [12] * 4 + [10] * 4 + [9]),
        quarters('SHRINK', 'operating_income', [1] * 9),
    ])
    data = ScreenData.from_panels('2020-06-30', closes, volumes, fundamentals=funds)
    assert ExampleFundamentalScreen().select(data)['symbol'].tolist() == ['GROW']


def test_database_securities_and_restated_fundamentals(sqlite_db):
    db = sqlite_db({})
    db.upsert_securities(pd.DataFrame({'symbol': ['AAA'], 'type': ['CS'], 'list_date': ['2010-01-04']}))
    db.upsert_securities(pd.DataFrame({'symbol': ['AAA'], 'type': ['CS'], 'name': ['Aaa Inc']}))
    assert db.get_securities().loc[0, 'name'] == 'Aaa Inc'

    original = quarters('AAA', 'revenue', [100])
    restated = original.assign(value=90, available_date=original['available_date'] + pd.Timedelta(days=200))
    assert db.insert_fundamentals(original) == 1
    assert db.insert_fundamentals(pd.concat([original, restated])) == 1   # only the new version
    first_public = original['available_date'].iloc[0]

    closes, volumes = panels(['AAA'])
    for asof, expected in ((first_public + pd.Timedelta(days=1), 100),
                           (first_public + pd.Timedelta(days=250), 90)):
        rows = db.get_fundamentals(asof)
        data = ScreenData(pd.Timestamp(asof), closes, volumes, fundamentals=rows)
        assert data.latest(['revenue'], max_age_days=10_000).loc['AAA', 'revenue'] == expected
