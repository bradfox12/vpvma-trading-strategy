import numpy as np
import pandas as pd
import pytest

import config
import factor_model as fm
from tests.conftest import make_ohlcv


@pytest.fixture(autouse=True)
def return_winners(monkeypatch):
    """Synthetic histories below define winners by return unless a test says otherwise"""
    monkeypatch.setattr(config, 'LEADERS_WINNER_DEFINITION', 'return')
    monkeypatch.setattr(config, 'LEADERS_SIZE_WEIGHT_CAP', None)
    monkeypatch.setattr(config, 'LEADERS_SPLIT', None)


def quarters(symbol, field, values, first_period='2022-03-31', lag_days=40):
    periods = pd.date_range(first_period, periods=len(values), freq='QE')
    return pd.DataFrame({'symbol': symbol, 'field': field, 'period_end': periods,
                         'available_date': periods + pd.Timedelta(days=lag_days), 'value': values})


def panels(symbols, volume=1_000_000, start='2022-01-03', end='2024-06-28'):
    dates = pd.bdate_range(start, end)
    closes = pd.DataFrame({s: make_ohlcv(dates, i).set_index('timestamp')['close'] for i, s in enumerate(symbols)})
    volumes = pd.DataFrame(volume, index=dates, columns=symbols, dtype=float)
    return closes, volumes


def test_tradeable_uses_20_day_average_shares():
    closes, volumes = panels(['AAA', 'BBB', 'SPY'])
    volumes['BBB'] = 200_000
    volumes.loc[volumes.index[-20:], 'BBB'] = 260_000         # only the last 20 sessions count
    assert list(fm.tradeable(closes, volumes, '2024-06-28')) == ['AAA', 'BBB']
    volumes.loc[volumes.index[-1], 'BBB'] = 0                   # 20-day average now just under 250k
    assert list(fm.tradeable(closes, volumes, '2024-06-28')) == ['AAA']


def test_fundamental_traits_point_in_time_and_bank_fallback():
    closes, volumes = panels(['GROW', 'BANK', 'GAP'])
    funds = pd.concat([
        quarters('GROW', 'revenue', [10, 10, 10, 10, 12, 12, 12, 15]),     # last quarter public 2024-02-09
        quarters('GROW', 'gross_profit', [5, 5, 5, 5, 6, 6, 6, 9]),
        quarters('GROW', 'net_income', [1, 1, 1, 1, 2, 2, 2, 2]),
        quarters('BANK', 'net_interest_income', [8] * 4 + [9] * 4),
        quarters('BANK', 'noninterest_income', [2] * 8),
        quarters('GAP', 'revenue', [10, 10, 10, 10, 12, 12, 12, 15]).drop(index=[5]),   # missing a quarter
    ])
    syms = pd.Index(['GROW', 'BANK', 'GAP'])
    before = fm.compute_traits(closes, volumes, funds, '2024-02-01', syms)
    after = fm.compute_traits(closes, volumes, funds, '2024-02-15', syms)
    assert np.isnan(before.at['GROW', 'rev_growth'])                 # 8th quarter not filed yet
    assert after.at['GROW', 'rev_growth'] == pytest.approx(51 / 40 - 1)
    assert after.at['GROW', 'gross_margin'] == pytest.approx(27 / 51)
    assert after.at['GROW', 'gross_margin_trend'] == pytest.approx(27 / 51 - 20 / 40)
    assert after.at['GROW', 'earnings_growth'] == pytest.approx(1.0)
    assert after.at['BANK', 'rev_growth'] == pytest.approx(44 / 40 - 1)  # NII + non-interest income
    assert np.isnan(after.at['GAP', 'rev_growth'])                   # non-consecutive quarters


def test_forward_returns_include_delistings_and_wait_for_horizon():
    dates = pd.bdate_range('2022-01-03', '2023-06-30')
    closes = pd.DataFrame({'A': np.linspace(10, 20, len(dates)), 'B': np.linspace(10, 5, len(dates))}, index=dates)
    closes.loc['2022-07-01':, 'B'] = np.nan                           # B delisted mid-year
    r = fm.forward_returns(closes, pd.Timestamp('2022-01-03'), ['A', 'B'])
    assert r['A'] > 0.5 and r['B'] < 0
    assert fm.forward_returns(closes, pd.Timestamp('2023-01-03'), ['A']).isna().all()


def synthetic_history(n_dates=24, n=200, good='price_strength', bad='size'):
    rng = np.random.default_rng(0)
    rows = []
    for d in pd.date_range('2012-01-01', periods=n_dates, freq='QS'):
        pct = pd.DataFrame(rng.random((n, len(fm.TRAITS))), columns=fm.TRAITS)
        pct['fwd_return'] = pct[good] - 0.5 * pct[bad] + 0.1 * rng.standard_normal(n)
        pct['date'], pct['symbol'] = d, [f'S{i}' for i in range(n)]
        rows.append(pct)
    return pd.concat(rows, ignore_index=True)


def test_weights_learn_signal_and_zero_negative(monkeypatch):
    monkeypatch.setattr(config, 'LEADERS_ZERO_NEGATIVE_WEIGHTS', True)
    w = fm.learn_weights(synthetic_history(), pd.Timestamp('2018-01-01'))
    assert w.idxmax() == 'price_strength' and w['size'] == 0 and w.sum() == pytest.approx(1)
    monkeypatch.setattr(config, 'LEADERS_ZERO_NEGATIVE_WEIGHTS', False)
    assert fm.learn_weights(synthetic_history(), pd.Timestamp('2018-01-01'))['size'] < 0


def test_weights_never_use_outcomes_unknown_at_the_time():
    history = synthetic_history()
    asof = pd.Timestamp('2015-01-01')
    w = fm.learn_weights(history, asof)
    # flip the relationship for every quarter whose 12-month outcome ended after `asof`
    late = history['date'] + pd.Timedelta(days=config.LEADERS_HORIZON_DAYS) > asof
    flipped = history.copy()
    flipped.loc[late, 'fwd_return'] = -flipped.loc[late, 'fwd_return']
    pd.testing.assert_series_equal(w, fm.learn_weights(flipped, asof))
    # no completed quarters yet -> equal weights
    assert fm.learn_weights(history, pd.Timestamp('2012-06-01')).nunique() == 1


def test_leaders_screen_same_result_from_database_and_backtest_panels(sqlite_db, monkeypatch):
    from screens import LeadersScreen, ScreenData
    dates = pd.bdate_range('2022-01-03', '2024-06-28')
    frames = {f'S{i}': make_ohlcv(dates, i) for i in range(12)}
    frames['SPY'] = make_ohlcv(dates, 99)
    db = sqlite_db(frames)
    funds = pd.concat([quarters(f'S{i}', 'revenue', list(10 + np.arange(8) * (i % 4))) for i in range(12)])
    db.insert_fundamentals(funds)
    monkeypatch.setattr(config, 'LEADERS_SIZE', 5)
    screen = LeadersScreen(history=synthetic_history())

    asof = pd.Timestamp('2024-04-01')
    closes = pd.DataFrame({s: f.set_index('timestamp')['close'] for s, f in frames.items()})
    volumes = pd.DataFrame({s: f.set_index('timestamp')['volume'] for s, f in frames.items()})
    from_panels = screen.select(ScreenData.from_panels(asof, closes, volumes, fundamentals=funds))
    from_db = screen.select(ScreenData.from_db(db, asof, screen.fields))
    pd.testing.assert_frame_equal(from_panels.reset_index(drop=True), from_db.reset_index(drop=True))
    assert len(from_panels) == 5 and 'SPY' not in set(from_panels['symbol'])


def test_contribution_winners_are_big_dollar_gainers(monkeypatch):
    monkeypatch.setattr(config, 'LEADERS_WINNER_DEFINITION', 'contribution')
    monkeypatch.setattr(config, 'LEADERS_WINNER_PCT', 0.5)
    h = pd.DataFrame({'date': pd.Timestamp('2015-01-01'), 'symbol': ['BIG', 'SMALL'],
                      'size_raw': np.log([1e12, 1e9]), 'fwd_return': [0.10, 2.0]})
    assert fm.label_winners(h).tolist() == [True, False]    # +$100B beats +$2B


def test_size_cap_rescales_other_weights():
    w = fm.learn_weights(synthetic_history(good='size', bad='rev_growth'), pd.Timestamp('2018-01-01'), size_cap=0.3)
    assert w['size'] == pytest.approx(0.3) and w.sum() == pytest.approx(1)
    w = fm.learn_weights(synthetic_history(), pd.Timestamp('2018-01-01'), exclude=('size', 'price_strength'))
    assert w['size'] == 0 and w['price_strength'] == 0 and w.sum() == pytest.approx(1)


def test_split_universe_adds_smaller_companies():
    rng = np.random.default_rng(1)
    raw = pd.DataFrame(rng.random((60, len(fm.TRAITS))), columns=fm.TRAITS, index=[f'S{i}' for i in range(60)])
    raw['size'] = np.log(np.linspace(1e9, 1e11, 60))            # S0 smallest ... S59 largest
    history = synthetic_history(good='size', bad='rev_growth')
    out = fm.select_universe(raw, history, pd.Timestamp('2018-01-01'), size=20,
                             split={'core': 10, 'emerging': 5, 'emerging_max_value': 2e10})
    assert len(out) == 15 and out.is_monotonic_decreasing
    core, emerging = out.index[:10], out.index[10:]
    assert all(np.exp(raw.loc[emerging, 'size']) < 2e10)
    assert not set(core) & set(emerging)
