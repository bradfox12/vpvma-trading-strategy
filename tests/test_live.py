import io
import json
import logging
import shutil

import pandas as pd
import pytest

import config
from tests.conftest import FakeDB, make_ohlcv


def test_regime_uses_full_200_day_ma():
    from protection.market_regime import detect_bear_regime
    dates = pd.bdate_range('2019-01-01', '2020-12-31')
    spy = make_ohlcv(dates, 1)
    # strong downtrend at the end -> below 200MA
    spy.loc[spy.index[-60:], ['open', 'high', 'low', 'close']] *= 0.6
    assert detect_bear_regime(FakeDB({'SPY': spy}), dates[-1]) is True


def test_logging_survives_unencodable_console(tmp_path, monkeypatch):
    import logging_setup
    stream = io.TextIOWrapper(io.BytesIO(), encoding='cp1252')
    monkeypatch.setattr(logging_setup, 'LOG_DIR', tmp_path)
    monkeypatch.setattr('sys.stdout', stream)
    logger = logging_setup.setup_logging('t')
    logger.info('📊 Universe ✅')
    stream.flush()
    assert '?' in stream.buffer.getvalue().decode('cp1252')
    assert '📊 Universe ✅' in (tmp_path / 't.log').read_text(encoding='utf-8')
    logging.getLogger().handlers.clear()


def test_tracker_migration_reads_values_not_formulas():
    from daily_portfolio_manager import TRACKER_FILE, _read_tracker
    positions, realized = _read_tracker(TRACKER_FILE)
    assert len(positions) == 18
    assert realized == pytest.approx(7736.06, abs=0.01)


@pytest.fixture
def pm_env(tmp_path, monkeypatch, make_frames, sqlite_db):
    import daily_portfolio_manager as dpm
    import screens
    from tests.conftest import TopVolumeScreen
    frames, spy = make_frames(n_symbols=40, start='2018-01-01', end='2020-12-31')
    frames['SPY'] = spy
    db = sqlite_db(frames)
    db.frames = frames
    screen = TopVolumeScreen(25)
    monkeypatch.setitem(screens.SCREENS, screen.name, screen)
    monkeypatch.setattr(config, 'SCREEN_NAME', screen.name)
    monkeypatch.setattr(dpm, 'STATE_FILE', tmp_path / 'state.json')
    monkeypatch.setattr(dpm, 'UNIVERSE_CACHE_FILE', tmp_path / 'universe.json')
    monkeypatch.setattr(dpm, 'TRACKER_FILE', tmp_path / 'missing.xlsx')
    monkeypatch.setattr(dpm, 'REPORT_FILE', tmp_path / 'orders.html')
    clock = {'now': pd.Timestamp('2020-12-31')}
    monkeypatch.setattr(dpm, 'datetime', type('D', (), {'now': staticmethod(lambda: clock['now'])}))
    return dpm, db, tmp_path, clock


def test_portfolio_manager_daily_runs(pm_env):
    dpm, db, tmp, clock = pm_env
    days = pd.bdate_range('2020-11-16', '2020-12-31')
    for day in days:
        clock['now'] = day
        assert dpm.PortfolioManager(db).run() == 0
        state = json.loads((tmp / 'state.json').read_text())
        assert state['last_run_data_date'] == day.strftime('%Y-%m-%d')
        assert state['cash'] >= 0
        assert len(state['positions']) <= config.MAX_POSITIONS
    assert len(state['positions']) > 0

    # rerun for the same date is a no-op
    before = (tmp / 'state.json').read_text()
    assert dpm.PortfolioManager(db).run() == 0
    assert (tmp / 'state.json').read_text() == before
    assert json.loads((tmp / 'universe.json').read_text())['period'] == '2020Q4'


def test_dry_run_saves_nothing(pm_env):
    dpm, db, tmp, _ = pm_env
    assert dpm.PortfolioManager(db).run(dry_run=True) == 0
    assert not (tmp / 'state.json').exists()


def test_live_decisions_match_backtest(pm_env, monkeypatch):
    """Day-by-day live runs make the same buy/sell decisions as the backtest"""
    from backtest import run_backtest_on_frames
    from tests.conftest import TopVolumeScreen
    dpm, db, tmp, clock = pm_env

    days = pd.bdate_range('2020-09-01', '2020-12-31')
    live = {}
    for day in days:
        clock['now'] = day
        pm = dpm.PortfolioManager(db)
        assert pm.run() == 0
        live[day] = ({t['symbol'] for t in pm.closed_trades},
                     set(pm.new_positions) | set(pm.replaced_positions))

    frames = {s: f for s, f in db.frames.items() if s != 'SPY'}
    res = run_backtest_on_frames(frames, db.frames['SPY'], days[0], days[-1], 100_000,
                                 screen=TopVolumeScreen(25))
    trades = res['trades']
    signal_day = {d: days[i - 1] for i, d in enumerate(days) if i > 0}
    backtest = {d: (set(), set()) for d in days}
    for _, t in trades.iterrows():
        side = 0 if t['action'] == 'SELL' else 1
        backtest[signal_day[t['date']]][side].add(t['symbol'])

    traded_days = 0
    for day in days[:-1]:
        assert live[day] == backtest[day], day.date()
        traded_days += bool(live[day][0] or live[day][1])
    assert traded_days > 10
