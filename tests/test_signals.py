import numpy as np
import pytest

import config
from main import calculate_vpvma_indicator
from signals.signal_generator import (
    buy_threshold,
    combine_signals,
    generate_buy_signals,
    generate_sell_signals,
    is_sell,
    sell_threshold,
)
from tests.conftest import make_ohlcv
import pandas as pd


def test_thresholds_match_original_formula_for_positive_signal_line():
    vpvmas = np.array([1.0, 5.0, 100.0])
    np.testing.assert_allclose(buy_threshold(vpvmas, 0.18), (1 + 0.18) * vpvmas)
    np.testing.assert_allclose(sell_threshold(vpvmas, 0.08), (1 - 0.16) * vpvmas)


def test_bands_stay_on_correct_side_for_negative_signal_line():
    vpvmas = np.array([-10.0, -1.0])
    assert np.all(buy_threshold(vpvmas, 0.18) > vpvmas)
    assert np.all(sell_threshold(vpvmas, 0.08) < vpvmas)


def test_buy_never_fires_below_signal_line_and_sell_never_above():
    dates = pd.bdate_range('2015-01-01', periods=1500)
    for seed in range(20):
        df = make_ohlcv(dates, seed)
        r = calculate_vpvma_indicator(df['high'].values, df['low'].values, df['close'].values,
                                      df['open'].values, df['volume'].values)
        assert np.nanmin(r['vpvmas']) < 0  # the case that used to invert
        assert not np.any(r['buy_signals'] & (r['vpvma'] <= r['vpvmas']))
        assert not np.any(r['sell_signals'] & (r['vpvma'] >= r['vpvmas']))


def test_warmup_nans_never_signal():
    vpvma = np.array([np.nan, np.nan, 1.0, 3.0])
    vpvmas = np.array([np.nan, np.nan, 2.0, 2.0])
    assert generate_buy_signals(vpvma, vpvmas, 0.1).tolist() == [False, False, False, True]
    assert not generate_sell_signals(vpvma, vpvmas, 0.08).any()


def test_scalar_is_sell_matches_vector_rule():
    dates = pd.bdate_range('2015-01-01', periods=800)
    df = make_ohlcv(dates, 3)
    r = calculate_vpvma_indicator(df['high'].values, df['low'].values, df['close'].values,
                                  df['open'].values, df['volume'].values)
    for bw in (config.SELL_BANDWIDTH, config.BEAR_SELL_BANDWIDTH):
        vec = generate_sell_signals(r['vpvma'], r['vpvmas'], bw)
        scalar = [False] + [is_sell(r['vpvma'][t - 1], r['vpvmas'][t - 1], r['vpvma'][t], r['vpvmas'][t], bw)
                            for t in range(1, len(dates))]
        assert vec.tolist() == scalar


def test_combine_signals_rejects_conflicts():
    with pytest.raises(ValueError):
        combine_signals(np.array([True]), np.array([True]))
