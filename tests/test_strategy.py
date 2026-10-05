from datetime import timedelta

import numpy as np
import pandas as pd

import config
from strategy import SymbolSignal, compute_indicator_frame, plan_day, rank_by_momentum, shares_for, symbol_signal
from tests.conftest import make_ohlcv


def sig(symbol, price=10.0, buy=False, strength=0.0, sell=False):
    # sell=True builds a crossover below the sell threshold
    if sell:
        return SymbolSignal(symbol, price, vpvma=0.5, vpvmas=1.0, vpvma_prev=1.1, vpvmas_prev=1.0,
                            buy_signal=False, strength=-0.6)
    return SymbolSignal(symbol, price, vpvma=1.0, vpvmas=1.0, vpvma_prev=1.0, vpvmas_prev=1.0,
                        buy_signal=buy, strength=strength)


def test_live_lookback_matches_full_history():
    """Signals from the live INDICATOR_LOOKBACK_DAYS window equal full-history values"""
    dates = pd.bdate_range('2010-01-01', '2020-12-31')
    mismatches = 0
    for seed in range(5):
        df = make_ohlcv(dates, seed)
        full = compute_indicator_frame(df)
        for t in dates[-250::10]:
            window = df[(df['timestamp'] > t - timedelta(days=config.INDICATOR_LOOKBACK_DAYS))
                        & (df['timestamp'] <= t)]
            live = symbol_signal('X', window)
            ref = full.loc[t]
            assert abs(live.vpvmas - ref['vpvmas']) <= 1e-4 * max(1.0, abs(ref['vpvmas']))
            mismatches += live.buy_signal != bool(ref['buy_signal'])
    assert mismatches == 0


def test_universe_drop_and_signal_sells():
    held = {'A': {'entry_price': 10}, 'B': {'entry_price': 10}, 'C': {'entry_price': 10}}
    signals = {'A': sig('A'), 'B': sig('B', sell=True), 'C': sig('C')}
    plan = plan_day(held, signals, spy_bearish=False, universe=['A', 'B'])
    reasons = {s['symbol']: s['reason'] for s in plan.sells}
    assert reasons == {'B': 'Signal', 'C': 'Universe Drop'}


def test_buys_ranked_capped_and_exclude_held():
    held = {f'H{i}': {'entry_price': 10} for i in range(18)}
    signals = {s: sig(s) for s in held}
    signals.update({'X': sig('X', buy=True, strength=0.1), 'Y': sig('Y', buy=True, strength=0.5),
                    'Z': sig('Z', buy=True, strength=0.3), 'H0': sig('H0', buy=True, strength=9)})
    plan = plan_day(held, signals, spy_bearish=False, max_positions=20)
    assert plan.buys == ['Y', 'Z']
    assert plan.missed_signals == 1


def test_replacement_only_for_losers_when_full():
    held = {f'H{i}': {'entry_price': 10} for i in range(20)}
    signals = {s: sig(s, price=11, strength=-0.2) for s in held}
    signals['H5'] = sig('H5', price=9, strength=-0.2)     # loser
    signals['N'] = sig('N', buy=True, strength=0.3)
    plan = plan_day(held, signals, spy_bearish=False, max_positions=20, enable_replacement=True)
    assert plan.replacements == [{'sell_symbol': 'H5', 'buy_symbol': 'N', 'improvement': 2.5}]
    assert plan.buys == []


def test_rank_by_momentum_uses_only_data_up_to_asof():
    idx = pd.bdate_range('2020-01-01', periods=40)
    up = pd.Series(np.linspace(10, 20, 40), index=idx)
    down = pd.Series(np.linspace(20, 10, 40), index=idx)
    late = pd.Series(np.r_[np.full(30, 10.0), np.full(10, 100.0)], index=idx)  # jumps after asof
    ranked = rank_by_momentum({'UP': up, 'DOWN': down, 'LATE': late}, idx[25], period=20, size=2)
    assert ranked['symbol'].tolist() == ['UP', 'LATE']
    assert ranked.loc[1, 'momentum_score'] == 0


def test_shares_for_respects_cash_and_commission():
    assert shares_for(equity=100_000, price=100, cash=100_000) == int((5000 - config.COMMISSION) / 100)
    assert shares_for(equity=100_000, price=100, cash=1000) == int((1000 - config.COMMISSION) / 100)
    assert shares_for(equity=100_000, price=0, cash=1000) == 0
