from datetime import datetime

import pandas as pd
import pytest

from daily_update import DailyDataUpdater, MarketDataClient, last_completed_session_candidate, MARKET_TZ
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


class FakeClient:
    """Stands in for MarketDataClient; serves canned sessions/actions"""

    def __init__(self, sessions, splits=None, dividends=None):
        self.sessions, self._splits, self._dividends = sessions, splits or {}, dividends or {}
        self.calls = []

    def grouped_daily(self, date):
        self.calls.append(date)
        rows = self.sessions.get(f"{date:%Y-%m-%d}", [])
        return pd.DataFrame(rows, columns=['symbol', 'open', 'high', 'low', 'close', 'volume'])

    def splits(self, date):
        return self._splits.get(f"{date:%Y-%m-%d}", [])

    def dividends(self, date):
        return self._dividends.get(f"{date:%Y-%m-%d}", [])


def bar(symbol, close):
    return {'symbol': symbol, 'open': close, 'high': close * 1.01, 'low': close * 0.99,
            'close': close, 'volume': 1_000_000}


def et(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=MARKET_TZ)


def test_insert_bars_skips_existing_rows(loaded_db):
    df = loaded_db.get_ohlcv_data('AAA').tail(2)
    again = df.assign(symbol='AAA')
    assert loaded_db.insert_bars(again) == 0
    assert len(loaded_db.get_ohlcv_data('AAA')) == len(pd.bdate_range('2024-01-01', '2024-03-01'))


def test_split_adjustment_is_applied_once(loaded_db):
    before = loaded_db.get_ohlcv_data('AAA')
    assert loaded_db.apply_adjustment('AAA', '2024-02-01', 'split', 0.5)
    assert not loaded_db.apply_adjustment('AAA', '2024-02-01', 'split', 0.5)
    after = loaded_db.get_ohlcv_data('AAA')
    pre = before['timestamp'] < '2024-02-01'
    assert after.loc[pre, 'close'].tolist() == pytest.approx((before.loc[pre, 'close'] * 0.5).tolist())
    assert after.loc[pre, 'volume'].tolist() == pytest.approx((before.loc[pre, 'volume'] * 2).tolist(), abs=1)
    assert after.loc[~pre, 'close'].tolist() == pytest.approx(before.loc[~pre, 'close'].tolist())


def test_session_candidate_uses_eastern_close():
    assert last_completed_session_candidate(et(2024, 3, 6, 16, 45)) == pd.Timestamp('2024-03-06')
    assert last_completed_session_candidate(et(2024, 3, 6, 12, 0)) == pd.Timestamp('2024-03-05')
    assert last_completed_session_candidate(et(2024, 3, 4, 9, 0)) == pd.Timestamp('2024-03-01')   # Monday am
    assert last_completed_session_candidate(et(2024, 3, 9, 20, 0)) == pd.Timestamp('2024-03-08')  # Saturday


def test_backfill_holiday_split_and_dividend(loaded_db):
    last_aaa = loaded_db.get_ohlcv_data('AAA')['close'].iloc[-1]
    last_bbb = loaded_db.get_ohlcv_data('BBB')['close'].iloc[-1]
    client = FakeClient(
        sessions={
            '2024-03-04': [bar('SPY', 500), bar('AAA', last_aaa / 2), bar('BBB', last_bbb), bar('ZZZ', 1)],
            # 2024-03-05 holiday: no bars
            '2024-03-06': [bar('SPY', 501), bar('AAA', last_aaa / 2), bar('BBB', last_bbb)],
        },
        splits={'2024-03-04': [{'ticker': 'AAA', 'split_from': 1, 'split_to': 2}]},
        dividends={'2024-03-06': [{'ticker': 'BBB', 'cash_amount': last_bbb * 0.01, 'currency': 'USD'}]},
    )
    updater = DailyDataUpdater(loaded_db, client)
    stats = updater.update(now=et(2024, 3, 6, 17, 0))

    assert stats == {'sessions': 2, 'holidays': 1, 'bars': 6, 'actions': 2, 'missing': {}}
    aaa = loaded_db.get_ohlcv_data('AAA')
    assert aaa['close'].iloc[-3] == pytest.approx(last_aaa / 2)       # history halved by the split
    assert aaa['close'].pct_change().abs().max() < 0.2                  # no artificial -50% gap
    assert 'ZZZ' not in loaded_db.list_symbols()                        # only tracked symbols stored
    bbb = loaded_db.get_ohlcv_data('BBB')
    assert bbb['close'].iloc[-3] == pytest.approx(last_bbb * 0.99)      # dividend back-adjusted

    # rerun: nothing to fetch, nothing re-applied
    client.calls.clear()
    assert updater.update(now=et(2024, 3, 6, 17, 0))['sessions'] == 0
    assert client.calls == []


def test_update_aborts_without_spy(loaded_db):
    client = FakeClient(sessions={'2024-03-04': [bar('AAA', 10)]})
    with pytest.raises(RuntimeError, match='no SPY'):
        DailyDataUpdater(loaded_db, client).update(now=et(2024, 3, 4, 17, 0))
    assert loaded_db.latest_timestamp('AAA') == pd.Timestamp('2024-03-01')


def test_client_retries_rate_limit_then_follows_pagination():
    class Resp:
        def __init__(self, code, payload):
            self.status_code, self._payload, self.text = code, payload, ''

        def json(self):
            return self._payload

    responses = [Resp(429, {}), Resp(200, {'results': [1], 'next_url': 'https://x/page2'}),
                 Resp(200, {'results': [2]})]

    class Session:
        def get(self, url, params, timeout):
            return responses.pop(0)

    client = MarketDataClient('key', base_url='https://x', session=Session(), sleep=lambda s: None)
    assert client.get_all('/stocks/v1/splits', {}) == [1, 2]


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
    res = run_backtest(db, db.list_symbols(), '2019-06-01', '2020-12-31', 100_000, universe_size=20)
    assert res['metrics']['num_round_trips'] > 0
    assert res['history']['num_positions'].max() <= config.MAX_POSITIONS
