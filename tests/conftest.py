import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def make_ohlcv(dates, seed, drift=0.0004, vol=0.02):
    """Random-walk OHLCV with consistent bars (low <= open/close <= high)"""
    r = np.random.default_rng(seed)
    n = len(dates)
    close = 100 * np.exp(np.cumsum(r.normal(drift, vol, n)))
    open_ = close * np.exp(r.normal(0, vol / 2.5, n))
    high = np.maximum(open_, close) * np.exp(np.abs(r.normal(0, vol / 2.5, n)))
    low = np.minimum(open_, close) * np.exp(-np.abs(r.normal(0, vol / 2.5, n)))
    volume = r.integers(1_000_000, 5_000_000, n).astype(float)
    return pd.DataFrame({'timestamp': pd.DatetimeIndex(dates), 'open': open_, 'high': high,
                         'low': low, 'close': close, 'volume': volume})


class FakeDB:
    """In-memory stand-in for data.database.Database"""

    def __init__(self, frames):
        self.frames = {s: f.sort_values('timestamp').reset_index(drop=True) for s, f in frames.items()}

    def get_ohlcv_data(self, symbol, start_date=None, end_date=None, limit=None):
        df = self.frames.get(symbol)
        if df is None:
            return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        mask = pd.Series(True, index=df.index)
        if start_date is not None:
            mask &= df['timestamp'] >= pd.Timestamp(start_date)
        if end_date is not None:
            mask &= df['timestamp'] <= pd.Timestamp(end_date)
        out = df[mask].reset_index(drop=True)
        return out.head(limit) if limit else out

    def list_symbols(self):
        return sorted(self.frames)


@pytest.fixture
def make_frames():
    def _make(n_symbols=30, start='2018-01-01', end='2020-12-31', seed0=0):
        dates = pd.bdate_range(start, end)
        frames = {f'S{i:03d}': make_ohlcv(dates, seed0 + i) for i in range(n_symbols)}
        spy = make_ohlcv(dates, 10_000, drift=0.0003, vol=0.012)
        return frames, spy
    return _make
