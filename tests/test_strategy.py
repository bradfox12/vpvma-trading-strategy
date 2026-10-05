from datetime import timedelta

import numpy as np
import pandas as pd

import config
from strategy import SymbolSignal, compute_indicator_frame, plan_day, shares_for, symbol_signal
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
    assert plan.swap_streaks == {'X': 1}   # stronger than the weakest holding: waiting to confirm
    assert plan.missed_signals == 0


def full_book(strength=0.3, weakest=0.1):
    held = {f'H{i:02d}': {'entry_price': 10} for i in range(20)}
    signals = {s: sig(s, strength=strength) for s in held}
    signals['H05'] = sig('H05', strength=weakest)
    return held, signals


def add_candidates(signals, n, strength=1.0, buy=True):
    signals.update({f'N{i}': sig(f'N{i}', buy=buy, strength=strength + i / 100) for i in range(n)})


def test_holding_is_kept_until_it_ranks_below_25(monkeypatch):
    monkeypatch.setattr(config, 'SWAP_CONFIRM_DAYS', 1)
    monkeypatch.setattr(config, 'SWAP_EXIT_RANK', 25)
    held, signals = full_book()
    add_candidates(signals, 4)                    # H05 ranks 24 of 24 -> inside the buffer
    assert plan_day(held, signals, False).replacements == []

    add_candidates(signals, 5)                    # H05 ranks 25 -> still kept
    assert plan_day(held, signals, False).replacements == []

    add_candidates(signals, 6)                    # H05 ranks 26 -> swapped for the strongest candidate
    plan = plan_day(held, signals, False)
    assert [(r['sell_symbol'], r['sell_rank'], r['buy_symbol'], r['buy_rank'])
            for r in plan.replacements] == [('H05', 26, 'N5', 1)]


def test_swap_waits_for_confirmation(monkeypatch):
    monkeypatch.setattr(config, 'SWAP_CONFIRM_DAYS', 2)
    held, signals = full_book()
    add_candidates(signals, 6)
    day1 = plan_day(held, signals, False)
    assert day1.replacements == [] and len(day1.swap_streaks) == 6

    add_candidates(signals, 6, buy=False)         # day 2: no new crossover, still strong
    day2 = plan_day(held, signals, False, swap_streaks=day1.swap_streaks)
    assert [(r['sell_symbol'], r['buy_symbol'], r['confirm_days']) for r in day2.replacements] == [('H05', 'N5', 2)]


def test_candidate_outside_top_20_or_below_threshold_does_not_count(monkeypatch):
    monkeypatch.setattr(config, 'SWAP_CONFIRM_DAYS', 2)
    held, signals = full_book(strength=0.3, weakest=0.3)
    signals['LOW'] = sig('LOW', buy=True, strength=0.2)            # ranks 21 of 21
    assert plan_day(held, signals, False).swap_streaks == {}

    signals['LOW'] = sig('LOW', strength=-0.1)                     # fell below its buy threshold
    assert plan_day(held, signals, False, swap_streaks={'LOW': 1}).swap_streaks == {}


def test_max_swaps_per_day(monkeypatch):
    monkeypatch.setattr(config, 'SWAP_CONFIRM_DAYS', 1)
    held, signals = full_book(strength=0.1, weakest=0.1)
    add_candidates(signals, 10)                   # every holding ranks 11-30; 5 rank worse than 25
    monkeypatch.setattr(config, 'MAX_SWAPS_PER_DAY', None)
    assert len(plan_day(held, signals, False).replacements) == 5
    monkeypatch.setattr(config, 'MAX_SWAPS_PER_DAY', 2)
    assert len(plan_day(held, signals, False).replacements) == 2


def test_shares_for_respects_cash_and_commission():
    assert shares_for(equity=100_000, price=100, cash=100_000) == int((5000 - config.COMMISSION) / 100)
    assert shares_for(equity=100_000, price=100, cash=1000) == int((1000 - config.COMMISSION) / 100)
    assert shares_for(equity=100_000, price=0, cash=1000) == 0
