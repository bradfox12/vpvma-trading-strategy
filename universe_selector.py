"""
Universe Selector - live wrapper around screens.py

Runs the configured screen (config.SCREEN_NAME) on the first session of each
SCREEN_FREQUENCY period, using exactly the same point-in-time inputs as the
backtest (screens.ScreenData), and caches the result on disk so every daily run
in the period trades the same universe.

Usage:
    selector = UniverseSelector(db, cache_file='universe_cache.json')
    universe = selector.get_universe(data_date)
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from screens import Screen, ScreenData, get_screen, rebalance_key

logger = logging.getLogger(__name__)

# Refuse to re-screen when the latest session has bars for fewer than this
# fraction of the symbols that traded the session before (partial data update)
MIN_SESSION_COVERAGE = 0.8


class UniverseSelector:
    """Selects and caches the tradable universe for live trading"""

    def __init__(self, db, screen: Optional[Screen] = None, cache_file: Optional[Path] = None,
                 frequency: Optional[str] = None):
        self.db = db
        self.screen = screen or get_screen()
        self.frequency = frequency
        self.cache_file = Path(cache_file) if cache_file else None
        self._period = None
        self._symbols: Optional[List[str]] = None
        self._scores = pd.DataFrame(columns=['symbol', 'score'])
        self._load_cache()

    def _load_cache(self):
        if self.cache_file is None or not self.cache_file.exists():
            return
        try:
            data = json.loads(self.cache_file.read_text())
            if data.get('screen') != self.screen.name:
                logger.info("Cached universe used screen %r, now %r - will re-screen",
                            data.get('screen'), self.screen.name)
                return
            self._period = data['period']
            self._symbols = data['symbols']
            self._scores = pd.DataFrame(data.get('scores', []), columns=['symbol', 'score'])
            logger.info("Loaded cached universe %s (%d symbols)", self._period, len(self._symbols))
        except Exception:
            logger.exception("Could not read universe cache %s - will re-screen", self.cache_file)

    def _save_cache(self):
        if self.cache_file is None:
            return
        payload = {
            'period': self._period,
            'screen': self.screen.name,
            'symbols': self._symbols,
            'scores': self._scores.to_dict('records'),
            'saved_at': datetime.now().isoformat(timespec='seconds'),
        }
        tmp = self.cache_file.with_suffix('.tmp')
        tmp.write_text(json.dumps(payload, indent=2, default=float))
        tmp.replace(self.cache_file)

    def _session_complete(self, data: ScreenData) -> bool:
        closes = data.closes.loc[:data.asof]
        if len(closes) < 2:
            return True
        today, before = closes.iloc[-1].notna().sum(), closes.iloc[-2].notna().sum()
        if before and today < MIN_SESSION_COVERAGE * before:
            logger.error("Only %d symbols have a bar on %s vs %d the session before - data looks partial",
                         today, closes.index[-1].date(), before)
            return False
        return True

    def get_universe(self, date=None, force_refresh: bool = False) -> List[str]:
        """
        Tradable symbols for `date`'s period. Re-screens on a new period; keeps
        the previous universe if the latest data looks incomplete.
        """
        date = pd.Timestamp(date) if date is not None else pd.Timestamp.now().normalize()
        period = rebalance_key(date, self.frequency)
        if not force_refresh and self._period == period and self._symbols is not None:
            logger.info("Using cached universe %s (%d symbols)", period, len(self._symbols))
            return self._symbols

        logger.info("Screening universe for %s with %r using data up to %s",
                    period, self.screen.name, date.date())
        data = ScreenData.from_db(self.db, date, self.screen.fields)
        if not self._session_complete(data):
            logger.error("Keeping previous universe (%s). Fix the data update and rerun.", self._period)
            return self._symbols or []

        selected = self.screen.select(data)
        if selected.empty:
            logger.error("Screen returned no symbols - keeping previous universe (%s)", self._period)
            return self._symbols or []

        self._period, self._symbols, self._scores = period, selected['symbol'].tolist(), selected
        self._save_cache()
        logger.info("Universe %s: %d symbols, top 5 %s", period, len(self._symbols), self._symbols[:5])
        return self._symbols

    def get_universe_info(self) -> Dict:
        return {
            'period': self._period,
            'screen': self.screen.name,
            'size': len(self._symbols or []),
            'top_5': (self._symbols or [])[:5],
        }

    def is_in_universe(self, symbol: str) -> bool:
        return bool(self._symbols) and symbol in self._symbols


if __name__ == "__main__":
    from logging_setup import setup_logging
    from data.database import Database

    setup_logging('universe_selector')
    db = Database()
    latest = db.latest_timestamp('SPY')
    selector = UniverseSelector(db)
    universe = selector.get_universe(latest, force_refresh=True)
    print(f"{len(universe)} symbols for {selector.get_universe_info()['period']}: {universe[:20]}")
