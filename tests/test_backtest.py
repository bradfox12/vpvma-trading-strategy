import numpy as np
import pandas as pd
import pytest

import config
from backtest import run_backtest_on_frames, rebalance_dates
from tests.conftest import TopVolumeScreen


@pytest.fixture(scope='module')
def result():
    from tests.conftest import make_ohlcv
    dates = pd.bdate_range('2017-01-01', '2020-06-30')
    frames = {f'S{i:03d}': make_ohlcv(dates, i) for i in range(40)}
    frames['S001'] = frames['S001'].iloc[:600]  # stops trading mid-test
    spy = make_ohlcv(dates, 999, drift=0.0003, vol=0.012)
    return frames, spy, run_backtest_on_frames(frames, spy, '2018-01-01', '2020-06-30', 100_000, screen=TopVolumeScreen(25))


def test_portfolio_invariants(result):
    _, _, res = result
    h = res['history']
    assert h['num_positions'].max() <= config.MAX_POSITIONS
    assert h['cash'].min() >= -1e-6
    assert np.isfinite(res['metrics']['sharpe'])


def test_fills_happen_at_next_open_not_signal_close(result):
    frames, _, res = result
    trades = res['trades']
    buys = trades[trades['action'] == 'BUY'].head(20)
    for _, t in buys.iterrows():
        bar = frames[t['symbol']].set_index('timestamp').loc[t['date']]
        assert t['price'] == pytest.approx(bar['open'] * (1 + config.SLIPPAGE_BPS / 10000))


def test_no_lookahead(result):
    """Changing prices after a cutoff must not change any decision before it"""
    frames, spy, res = result
    cutoff = pd.Timestamp('2019-06-28')
    shocked = {}
    for sym, df in frames.items():
        df = df.copy()
        after = df['timestamp'] > cutoff
        df.loc[after, ['open', 'high', 'low', 'close']] *= 3.0
        shocked[sym] = df
    res2 = run_backtest_on_frames(shocked, spy, '2018-01-01', '2020-06-30', 100_000, screen=TopVolumeScreen(25))
    before = lambda t: t[t['date'] <= cutoff].reset_index(drop=True)
    pd.testing.assert_frame_equal(before(res['trades']), before(res2['trades']))


def test_position_in_stopped_symbol_is_closed(result):
    frames, _, res = result
    last_bar = frames['S001']['timestamp'].max()
    trades = res['trades'][res['trades']['symbol'] == 'S001']
    if len(trades) and trades.iloc[-1]['action'] == 'BUY':
        pytest.fail('S001 still held after its data stopped')
    assert not (trades['date'] > last_bar + pd.Timedelta(days=30)).any() or \
        trades.iloc[-1]['exit_reason'] == 'No Data'


def test_no_trades_does_not_crash():
    from tests.conftest import make_ohlcv
    dates = pd.bdate_range('2019-02-01', '2019-03-29')  # too short for indicator warmup
    frames = {'A': make_ohlcv(dates, 1)}
    spy = make_ohlcv(dates, 2)
    res = run_backtest_on_frames(frames, spy, '2019-03-01', '2019-03-29', 100_000)
    assert res['metrics']['num_trades'] == 0
    assert np.isnan(res['metrics']['win_rate'])


def test_universe_rebalances_quarterly_and_is_point_in_time(result):
    _, _, res = result
    dates = [h['date'] for h in res['universe_history']]
    assert dates[0] == pd.Timestamp('2018-01-01')  # synthetic calendar = weekdays
    assert all(d.month in (1, 4, 7, 10) for d in dates)
    assert len(dates) == 10  # 2018Q1 .. 2020Q2
    # every BUY is a symbol from the universe of its period (or the period
    # just ended, for orders decided on the last session before a rebalance)
    by_period = {h['date']: set(h['symbols']) for h in res['universe_history']}
    starts = sorted(by_period)
    trades = res['trades'][res['trades']['action'] == 'BUY']
    for _, t in trades.iterrows():
        prior = [d for d in starts if d <= t['date']]
        allowed = by_period[prior[-1]] | (by_period[prior[-2]] if len(prior) > 1 else set())
        assert t['symbol'] in allowed


def test_rebalance_dates_monthly():
    days = pd.bdate_range('2020-01-01', '2020-03-31')
    assert [d.month for d in rebalance_dates(days, 'monthly')] == [1, 2, 3]
