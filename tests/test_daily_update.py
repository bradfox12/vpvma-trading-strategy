import json
from datetime import datetime

import pandas as pd
import pytest

import daily_update
from daily_update import MARKET_TZ, TiingoDailyUpdater
from tests.conftest import make_ohlcv

LOADED_TO = pd.Timestamp('2024-03-01')       # last bar stored before the update
TARGET = pd.Timestamp('2024-03-06')
NOW = datetime(2024, 3, 6, 19, 0, tzinfo=MARKET_TZ)


def tiingo_bars(df):
    return df.assign(div_cash=0.0, split_factor=1.0)


class FakeTiingo:
    """Serves bars per permaTicker up to TARGET"""

    def __init__(self, histories):
        self.histories = histories
        self.calls = []

    def prices(self, perma, start='2008-01-01', end=None):
        self.calls.append((perma, pd.Timestamp(start)))
        df = self.histories[perma]
        mask = df['timestamp'] >= pd.Timestamp(start)
        if end is not None:
            mask &= df['timestamp'] <= pd.Timestamp(end)
        return df[mask].reset_index(drop=True)


def master(rows):
    return pd.DataFrame([{'symbol': r[1].replace('-', '.'), 'ticker': r[1], 'perma_ticker': r[0], 'name': r[1],
                          'is_active': r[2], 'exchange': 'NYSE', 'reused': False} for r in rows])


@pytest.fixture
def env(sqlite_db, tmp_path, monkeypatch):
    import daily_portfolio_manager as dpm
    import scripts.load_universe as lu
    dates = pd.bdate_range('2023-01-02', TARGET)
    histories = {p: tiingo_bars(make_ohlcv(dates, i)) for i, p in enumerate(['SPY', 'P1', 'P2', 'P3'])}
    db = sqlite_db({})
    for perma, symbol in (('SPY', 'SPY'), ('P1', 'AAA'), ('P2', 'BBB'), ('P3', 'CCC')):
        db.insert_ohlcv_data(symbol, histories[perma][histories[perma]['timestamp'] <= LOADED_TO], replace=True)
        db.upsert_securities(pd.DataFrame([{'symbol': symbol, 'type': 'ETF' if symbol == 'SPY' else 'CS',
                                            'list_date': dates[0], 'perma_ticker': perma}]))
    monkeypatch.setattr(dpm, 'STATE_FILE', tmp_path / 'state.json')
    monkeypatch.setattr(dpm, 'UNIVERSE_CACHE_FILE', tmp_path / 'universe.json')
    monkeypatch.setattr(lu, 'build_master', lambda *a, **k: master(
        [('SPY', 'SPY', True), ('P1', 'AAA', True), ('P2', 'BBB', True), ('P3', 'CCC', True)]))
    tiingo = FakeTiingo(histories)
    return db, tiingo, histories, monkeypatch, tmp_path


def run(db, tiingo):
    return TiingoDailyUpdater(db, tiingo, sec=None).run(now=NOW)


def test_appends_new_bars(env):
    db, tiingo, histories, *_ = env
    assert run(db, tiingo) == 0
    for symbol in ('SPY', 'AAA', 'BBB', 'CCC'):
        assert db.latest_timestamp(symbol) == TARGET
    assert all(start > LOADED_TO - pd.Timedelta(days=30) for _, start in tiingo.calls)   # no full reloads


def test_dividend_or_revision_triggers_full_reload(env):
    db, tiingo, histories, *_ = env
    h = histories['P1']
    h.loc[h['timestamp'] == pd.Timestamp('2024-03-05'), 'div_cash'] = 0.5          # dividend in new bars
    adjusted = h['timestamp'] < pd.Timestamp('2024-03-05')
    h.loc[adjusted, ['open', 'high', 'low', 'close']] *= 0.99                       # Tiingo back-adjusts history
    histories['P2'].loc[histories['P2']['timestamp'] == pd.Timestamp('2024-02-28'), 'close'] *= 1.01  # revision

    assert run(db, tiingo) == 0
    full = {perma for perma, start in tiingo.calls if start == pd.Timestamp('2008-01-01')}
    assert full == {'P1', 'P2'}
    stored = db.get_ohlcv_data('AAA')
    assert stored['close'].tolist() == pytest.approx(h['close'].tolist())


def test_ticker_change_renames_everywhere(env):
    db, tiingo, histories, monkeypatch, tmp = env
    import scripts.load_universe as lu
    (tmp / 'state.json').write_text(json.dumps({'cash': 1, 'positions': {'AAA': {'shares': 5}}}))
    (tmp / 'universe.json').write_text(json.dumps({'period': '2024Q1', 'screen': 'x', 'symbols': ['AAA', 'BBB']}))
    monkeypatch.setattr(lu, 'build_master', lambda *a, **k: master(
        [('SPY', 'SPY', True), ('P1', 'NEWA', True), ('P2', 'BBB', True), ('P3', 'CCC', True)]))

    assert run(db, tiingo) == 0
    assert 'NEWA' in db.list_symbols() and 'AAA' not in db.list_symbols()
    assert json.loads((tmp / 'state.json').read_text())['positions'] == {'NEWA': {'shares': 5}}
    assert json.loads((tmp / 'universe.json').read_text())['symbols'] == ['NEWA', 'BBB']


def test_new_listing_takes_ticker_from_delisted_company(env):
    db, tiingo, histories, monkeypatch, _ = env
    import scripts.load_universe as lu
    # CCC stopped trading long ago; a new company now uses the CCC ticker
    db.insert_ohlcv_data('CCC', histories['P3'][histories['P3']['timestamp'] <= '2023-06-30'], replace=True)
    db.upsert_securities(pd.DataFrame([{'symbol': 'CCC', 'type': 'CS', 'list_date': '2023-01-02',
                                        'delist_date': '2023-06-30', 'perma_ticker': 'P3'}]))
    dates = pd.bdate_range('2024-01-02', TARGET)
    histories['P9'] = tiingo_bars(make_ohlcv(dates, 9))
    monkeypatch.setattr(lu, 'build_master', lambda *a, **k: master(
        [('SPY', 'SPY', True), ('P1', 'AAA', True), ('P2', 'BBB', True), ('P3', 'CCC', False), ('P9', 'CCC', True)]))

    assert run(db, tiingo) == 0
    sec = db.get_securities().set_index('symbol')
    assert sec.at['CCC', 'perma_ticker'] == 'P9'
    assert sec.at['CCC~2023', 'perma_ticker'] == 'P3'
    assert db.latest_timestamp('CCC') == TARGET


def test_holiday_and_stale_data(env):
    db, tiingo, histories, *_ = env
    for perma in histories:                       # nobody traded on the target day (holiday)
        histories[perma] = histories[perma][histories[perma]['timestamp'] < TARGET]
    assert run(db, tiingo) == 0

    for perma in histories:                       # SPY far behind: data feed problem
        histories[perma] = histories[perma][histories[perma]['timestamp'] <= LOADED_TO]
    assert TiingoDailyUpdater(db, tiingo, None).run(now=datetime(2024, 3, 12, 19, 0, tzinfo=MARKET_TZ)) == 1


def test_fundamentals_refresh_only_recent_filers(env, monkeypatch, tmp_path):
    db, tiingo, *_ = env
    import data.sec_edgar as se
    db.set_security_ciks('AAA', [(111, 'test')])
    db.set_security_ciks('BBB', [(222, 'test')])
    monkeypatch.setattr(daily_update, 'EDGAR_STATE_FILE', tmp_path / 'edgar_state.json')
    (tmp_path / 'edgar_state.json').write_text(json.dumps({'last_index_date': '2024-03-04'}))
    monkeypatch.setattr(se, 'periodic_filers_on', lambda sec, d: {111, 999} if d == pd.Timestamp('2024-03-05') else set())

    class Sec:
        fetched = []

        def company_facts(self, cik):
            self.fetched.append(cik)
            return {'facts': {'us-gaap': {'Revenues': {'units': {'USD': [
                {'start': '2023-10-01', 'end': '2023-12-31', 'val': 5.0, 'filed': '2024-03-05', 'form': '10-Q'}]}}}}}

    sec = Sec()
    out = TiingoDailyUpdater(db, tiingo, sec).update_fundamentals(pd.Timestamp('2024-03-06'))
    assert sec.fetched == [111] and out['rows_added'] == 1
    assert json.loads((tmp_path / 'edgar_state.json').read_text())['last_index_date'] == '2024-03-06'
