import numpy as np
import pandas as pd
import pytest

import config
from backtest import run_backtest_on_frames


@pytest.fixture(scope='module')
def result():
    from tests.conftest import make_ohlcv
    dates = pd.bdate_range('2017-01-01', '2020-06-30')
    frames = {f'S{i:03d}': make_ohlcv(dates, i) for i in range(40)}
    frames['S001'] = frames['S001'].iloc[:600]  # stops trading mid-test
    spy = make_ohlcv(dates, 999, drift=0.0003, vol=0.012)
    return frames, spy, run_backtest_on_frames(frames, spy, '2018-01-01', '2020-06-30', 100_000, universe_size=25)


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
    res2 = run_backtest_on_frames(shocked, spy, '2018-01-01', '2020-06-30', 100_000, universe_size=25)
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
