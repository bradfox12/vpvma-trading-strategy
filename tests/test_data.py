from datetime import datetime

import pandas as pd
import pytest

from daily_update import last_completed_session_candidate, MARKET_TZ
from data.database import Database
from tests.conftest import make_ohlcv


@pytest.fixture
def db(tmp_path):
    database = Database(url=f"sqlite:///{tmp_path / 'test.db'}")
    database.create_tables()
    return database


@pytest.fixture
def loaded_db(db):
    dates = pd.bdate_range('2024-01-01', '2024-03-01')
    for i, sym in enumerate(['SPY', 'AAA', 'BBB']):
        db.insert_ohlcv_data(sym, make_ohlcv(dates, i), replace=True)
    return db


def et(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=MARKET_TZ)


def test_insert_bars_skips_existing_rows(loaded_db):
    df = loaded_db.get_ohlcv_data('AAA').tail(2)
    again = df.assign(symbol='AAA')
    assert loaded_db.insert_bars(again) == 0
    assert len(loaded_db.get_ohlcv_data('AAA')) == len(pd.bdate_range('2024-01-01', '2024-03-01'))


def test_session_candidate_uses_eastern_evening():
    assert last_completed_session_candidate(et(2024, 3, 6, 18, 30)) == pd.Timestamp('2024-03-06')
    assert last_completed_session_candidate(et(2024, 3, 6, 16, 45)) == pd.Timestamp('2024-03-05')
    assert last_completed_session_candidate(et(2024, 3, 4, 9, 0)) == pd.Timestamp('2024-03-01')   # Monday am
    assert last_completed_session_candidate(et(2024, 3, 9, 20, 0)) == pd.Timestamp('2024-03-08')  # Saturday


def test_validator_flags_bad_data(loaded_db):
    from scripts.validate_data import validate
    import config
    dates = pd.bdate_range('2023-01-02', '2024-03-01')
    loaded_db.insert_ohlcv_data('SPY', make_ohlcv(dates, 0), replace=True)
    bad = make_ohlcv(dates, 5)
    bad.loc[100, 'close'] = bad.loc[99, 'close'] * 2.5              # unadjusted-split-like jump
    bad.loc[100, 'high'] = bad.loc[100, 'close'] * 1.01
    bad.loc[200, 'low'] = bad.loc[200, 'high'] * 2                   # impossible bar
    bad = bad.drop(index=[150, 151]).iloc[:-10]                       # gaps + stale
    loaded_db.insert_ohlcv_data('BAD', bad, replace=True)

    issues = validate(loaded_db)
    checks = set(issues.loc[issues['symbol'] == 'BAD', 'check'])
    assert {'ohlc', 'jump', 'gaps', 'stale'} <= checks
    assert not (issues['symbol'] == 'SPY').any()


def test_backtest_runs_from_database(db):
    """run_backtest loads from a real database (SQLite) end to end"""
    import config
    from backtest import run_backtest
    dates = pd.bdate_range('2018-01-01', '2020-12-31')
    db.insert_ohlcv_data('SPY', make_ohlcv(dates, 99, drift=0.0003, vol=0.012), replace=True)
    for i in range(30):
        db.insert_ohlcv_data(f'S{i:02d}', make_ohlcv(dates, i), replace=True)
    from tests.conftest import TopVolumeScreen
    res = run_backtest(db, '2019-06-01', '2020-12-31', 100_000, screen=TopVolumeScreen(20))
    assert len(res['universe_history']) == 7
    assert res['metrics']['num_round_trips'] > 0
    assert res['history']['num_positions'].max() <= config.MAX_POSITIONS
