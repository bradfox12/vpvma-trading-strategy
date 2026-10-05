"""
Database connection and operations

Schema is defined with SQLAlchemy Core, so the same code runs on PostgreSQL
(production) and SQLite (tests, or a lightweight local setup).

Tables:
- ohlcv_data: one fully adjusted daily bar per (symbol, session date at midnight)
- corporate_actions: splits/dividends already applied to ohlcv_data, so an
  adjustment can never be applied twice
- securities: security master (type, exchange, listing dates, sector)
- fundamentals: point-in-time fundamentals keyed by the date they became public
"""

import logging
import os
from typing import Dict, List, Optional

import pandas as pd
from sqlalchemy import (
    BigInteger, Column, DateTime, Float, Index, Integer, MetaData, String, Table,
    UniqueConstraint, create_engine, func, select, text,
)

from secure_config import SecureConfig

logger = logging.getLogger(__name__)

metadata = MetaData()

ohlcv_table = Table(
    'ohlcv_data', metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('symbol', String(20), nullable=False),
    Column('timestamp', DateTime, nullable=False),
    Column('open', Float, nullable=False),
    Column('high', Float, nullable=False),
    Column('low', Float, nullable=False),
    Column('close', Float, nullable=False),
    Column('volume', BigInteger, nullable=False),
    Column('created_at', DateTime, server_default=func.current_timestamp()),
    UniqueConstraint('symbol', 'timestamp'),
    Index('idx_symbol_timestamp', 'symbol', 'timestamp'),
)

corporate_actions_table = Table(
    'corporate_actions', metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('symbol', String(20), nullable=False),
    Column('ex_date', DateTime, nullable=False),
    Column('kind', String(10), nullable=False),          # 'split' | 'dividend'
    Column('price_factor', Float, nullable=False),       # multiplier for prices before ex_date
    Column('details', String(200)),
    Column('applied_at', DateTime, server_default=func.current_timestamp()),
    UniqueConstraint('symbol', 'ex_date', 'kind'),
)

securities_table = Table(
    'securities', metadata,
    Column('symbol', String(20), primary_key=True),
    Column('name', String(200)),
    Column('type', String(20)),            # e.g. CS = common stock, ETF, PFD, ADRC
    Column('exchange', String(20)),
    Column('sector', String(100)),
    Column('industry', String(200)),
    Column('list_date', DateTime),
    Column('delist_date', DateTime),       # NULL while still listed
)

# Point-in-time fundamentals, long format: one row per (symbol, field, period,
# version). available_date is when that value became public (filing date);
# a restatement is a new row with a later available_date, so every screening
# date sees exactly the values public at the time.
fundamentals_table = Table(
    'fundamentals', metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('symbol', String(20), nullable=False),
    Column('field', String(60), nullable=False),
    Column('period_end', DateTime, nullable=False),
    Column('available_date', DateTime, nullable=False),
    Column('value', Float),
    UniqueConstraint('symbol', 'field', 'period_end', 'available_date'),
    Index('idx_fund_symbol_available', 'symbol', 'available_date'),
)

OHLCV_COLUMNS = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
SECURITY_COLUMNS = ['symbol', 'name', 'type', 'exchange', 'sector', 'industry', 'list_date', 'delist_date']
FUNDAMENTAL_COLUMNS = ['symbol', 'field', 'period_end', 'available_date', 'value']


class Database:
    """Storage and retrieval of daily OHLCV data"""

    def __init__(self, db_type: Optional[str] = None, url=None):
        """
        Args:
            db_type: 'postgresql' (credentials from .env) or 'sqlite' (data/trading_data.db);
                     default from DB_TYPE in .env, else 'postgresql'
            url: Explicit SQLAlchemy URL; overrides db_type (used by tests)
        """
        db_type = db_type or os.getenv('DB_TYPE', 'postgresql')
        self.db_type = db_type
        self.connection_url = url or SecureConfig.get_database_url(db_type)
        self.engine = create_engine(self.connection_url, echo=False)

    def create_tables(self):
        """Create missing tables (existing tables are left unchanged)"""
        metadata.create_all(self.engine)

    # ------------------------------------------------------------------ writes

    def insert_ohlcv_data(self, symbol: str, df: pd.DataFrame, replace: bool = False):
        """
        Insert bars for one symbol.

        Args:
            symbol: Ticker
            df: DataFrame with columns [timestamp, open, high, low, close, volume]
            replace: Delete the symbol's existing bars first (same transaction)
        """
        if not set(OHLCV_COLUMNS).issubset(df.columns):
            raise ValueError(f"DataFrame must contain columns: {OHLCV_COLUMNS}")
        df = df[OHLCV_COLUMNS].copy()
        df.insert(0, 'symbol', symbol)
        self.insert_bars(df, replace_symbols=[symbol] if replace else None)
        logger.info("Inserted %d records for %s", len(df), symbol)

    def insert_bars(self, bars: pd.DataFrame, replace_symbols: Optional[List[str]] = None) -> int:
        """
        Insert bars for many symbols in one transaction, skipping (symbol, timestamp)
        pairs that already exist.

        Args:
            bars: DataFrame [symbol, timestamp, open, high, low, close, volume]
            replace_symbols: Symbols whose existing bars are deleted first

        Returns:
            Number of rows inserted
        """
        if bars.empty:
            return 0
        bars = bars[['symbol'] + OHLCV_COLUMNS].copy()
        bars['timestamp'] = pd.to_datetime(bars['timestamp'])
        bars['volume'] = bars['volume'].round().astype('int64')

        with self.engine.begin() as conn:
            if replace_symbols:
                conn.execute(ohlcv_table.delete().where(ohlcv_table.c.symbol.in_(replace_symbols)))
            else:
                existing = pd.read_sql(
                    select(ohlcv_table.c.symbol, ohlcv_table.c.timestamp).where(
                        ohlcv_table.c.symbol.in_(bars['symbol'].unique().tolist()),
                        ohlcv_table.c.timestamp.between(bars['timestamp'].min().to_pydatetime(),
                                                        bars['timestamp'].max().to_pydatetime()),
                    ),
                    conn, parse_dates=['timestamp'],
                )
                if not existing.empty:
                    keys = set(zip(existing['symbol'], existing['timestamp']))
                    bars = bars[[k not in keys for k in zip(bars['symbol'], bars['timestamp'])]]
            if bars.empty:
                return 0
            conn.execute(ohlcv_table.insert(), bars.to_dict('records'))
        return len(bars)

    def apply_adjustment(self, symbol: str, ex_date, kind: str, price_factor: float, details: str = '') -> bool:
        """
        Back-adjust a symbol's bars before ex_date for a split or dividend.

        Prices are multiplied by price_factor and volume divided by it, matching
        how the historical loader adjusts EOD data. Recorded in corporate_actions
        in the same transaction; returns False if this action was already applied.
        """
        ex_date = pd.Timestamp(ex_date).to_pydatetime()
        if not (0 < price_factor < 100):
            raise ValueError(f"{symbol}: implausible {kind} factor {price_factor}")

        with self.engine.begin() as conn:
            already = conn.execute(
                select(corporate_actions_table.c.id).where(
                    corporate_actions_table.c.symbol == symbol,
                    corporate_actions_table.c.ex_date == ex_date,
                    corporate_actions_table.c.kind == kind,
                )
            ).first()
            if already:
                return False
            t = ohlcv_table.c
            conn.execute(
                ohlcv_table.update()
                .where(t.symbol == symbol, t.timestamp < ex_date)
                .values(open=t.open * price_factor, high=t.high * price_factor,
                        low=t.low * price_factor, close=t.close * price_factor,
                        volume=func.round(t.volume / price_factor))
            )
            conn.execute(corporate_actions_table.insert().values(
                symbol=symbol, ex_date=ex_date, kind=kind,
                price_factor=price_factor, details=details[:200],
            ))
        logger.info("%s: applied %s on %s (price factor %.6f) %s",
                    symbol, kind, ex_date.date(), price_factor, details)
        return True

    # ------------------------------------------------------------------- reads

    def get_ohlcv_data(self, symbol: str, start_date=None, end_date=None, limit: Optional[int] = None) -> pd.DataFrame:
        """
        Bars for one symbol, sorted chronologically.

        Args:
            symbol: Ticker
            start_date / end_date: Inclusive timestamp bounds (optional)
            limit: Maximum rows (optional)

        Returns:
            DataFrame [timestamp, open, high, low, close, volume] (floats)
        """
        t = ohlcv_table.c
        query = select(t.timestamp, t.open, t.high, t.low, t.close, t.volume).where(t.symbol == symbol)
        if start_date is not None:
            query = query.where(t.timestamp >= pd.Timestamp(start_date).to_pydatetime())
        if end_date is not None:
            query = query.where(t.timestamp <= pd.Timestamp(end_date).to_pydatetime())
        query = query.order_by(t.timestamp)
        if limit:
            query = query.limit(int(limit))

        df = pd.read_sql(query, self.engine, parse_dates=['timestamp'])
        for col in ('open', 'high', 'low', 'close', 'volume'):
            df[col] = df[col].astype(float)
        return df

    def list_symbols(self) -> List[str]:
        """All symbols in the database"""
        query = select(ohlcv_table.c.symbol).distinct().order_by(ohlcv_table.c.symbol)
        return pd.read_sql(query, self.engine)['symbol'].tolist()

    def symbol_ranges(self) -> pd.DataFrame:
        """Per-symbol [symbol, first, last, bars]"""
        t = ohlcv_table.c
        query = (select(t.symbol, func.min(t.timestamp).label('first'),
                        func.max(t.timestamp).label('last'), func.count().label('bars'))
                 .group_by(t.symbol).order_by(t.symbol))
        return pd.read_sql(query, self.engine, parse_dates=['first', 'last'])

    def latest_timestamp(self, symbol: str) -> Optional[pd.Timestamp]:
        value = pd.read_sql(
            select(func.max(ohlcv_table.c.timestamp).label('last')).where(ohlcv_table.c.symbol == symbol),
            self.engine, parse_dates=['last'],
        )['last'].iloc[0]
        return None if pd.isna(value) else pd.Timestamp(value)

    def get_bars(self, start_date, end_date, symbols: Optional[List[str]] = None,
                 columns=('close', 'volume')) -> pd.DataFrame:
        """
        Bars for many symbols in one query: [symbol, timestamp, *columns]

        Args:
            start_date / end_date: Inclusive bounds
            symbols: Restrict to these symbols (default: all)
            columns: OHLCV columns to return
        """
        t = ohlcv_table.c
        query = select(t.symbol, t.timestamp, *[t[c] for c in columns]).where(
            t.timestamp >= pd.Timestamp(start_date).to_pydatetime(),
            t.timestamp <= pd.Timestamp(end_date).to_pydatetime(),
        )
        if symbols is not None:
            query = query.where(t.symbol.in_(list(symbols)))
        df = pd.read_sql(query.order_by(t.symbol, t.timestamp), self.engine, parse_dates=['timestamp'])
        for col in columns:
            df[col] = df[col].astype(float)
        return df

    def upsert_securities(self, securities: pd.DataFrame) -> int:
        """Replace the rows for the given symbols in the securities master"""
        if securities.empty:
            return 0
        df = securities.reindex(columns=SECURITY_COLUMNS)
        for col in ('list_date', 'delist_date'):
            df[col] = pd.to_datetime(df[col])
        df = df.astype(object).where(df.notna(), None)
        with self.engine.begin() as conn:
            conn.execute(securities_table.delete().where(securities_table.c.symbol.in_(df['symbol'].tolist())))
            conn.execute(securities_table.insert(), df.to_dict('records'))
        return len(df)

    def get_securities(self) -> pd.DataFrame:
        """The securities master (empty if not loaded yet)"""
        return pd.read_sql(select(securities_table), self.engine, parse_dates=['list_date', 'delist_date'])

    def insert_fundamentals(self, rows: pd.DataFrame) -> int:
        """
        Insert point-in-time fundamentals [symbol, field, period_end, available_date, value].
        Rows already stored (same symbol, field, period_end, available_date) are
        skipped; restatements (later available_date) are added as new versions.
        """
        if rows.empty:
            return 0
        df = rows[FUNDAMENTAL_COLUMNS].copy()
        df['period_end'] = pd.to_datetime(df['period_end'])
        df['available_date'] = pd.to_datetime(df['available_date'])
        if df['available_date'].isna().any():
            raise ValueError("fundamentals rows need an available_date (filing date)")
        key = ['symbol', 'field', 'period_end', 'available_date']
        df = df.drop_duplicates(key, keep='last')
        f = fundamentals_table.c
        with self.engine.begin() as conn:
            existing = pd.read_sql(
                select(f.symbol, f.field, f.period_end, f.available_date).where(
                    f.symbol.in_(df['symbol'].unique().tolist())),
                conn, parse_dates=['period_end', 'available_date'])
            if not existing.empty:
                have = set(map(tuple, existing[key].to_numpy()))
                df = df[[tuple(r) not in have for r in df[key].to_numpy()]]
            if df.empty:
                return 0
            conn.execute(fundamentals_table.insert(), df.astype(object).where(df.notna(), None).to_dict('records'))
        return len(df)

    def get_fundamentals(self, available_by, since=None, symbols: Optional[List[str]] = None) -> pd.DataFrame:
        """
        Fundamentals rows public on or before `available_by` (optionally after `since`)

        Returns:
            DataFrame [symbol, field, period_end, available_date, value]
        """
        f = fundamentals_table.c
        query = select(*[f[c] for c in FUNDAMENTAL_COLUMNS]).where(
            f.available_date <= pd.Timestamp(available_by).to_pydatetime())
        if since is not None:
            query = query.where(f.available_date > pd.Timestamp(since).to_pydatetime())
        if symbols is not None:
            query = query.where(f.symbol.in_(list(symbols)))
        return pd.read_sql(query, self.engine, parse_dates=['period_end', 'available_date'])

    def last_closes_before(self, symbols: List[str], date) -> Dict[str, float]:
        """Most recent close strictly before `date` for each symbol"""
        t = ohlcv_table.c
        date = pd.Timestamp(date).to_pydatetime()
        latest = (select(t.symbol, func.max(t.timestamp).label('ts'))
                  .where(t.symbol.in_(symbols), t.timestamp < date)
                  .group_by(t.symbol).subquery())
        query = select(t.symbol, t.close).join(
            latest, (t.symbol == latest.c.symbol) & (t.timestamp == latest.c.ts))
        df = pd.read_sql(query, self.engine)
        return dict(zip(df['symbol'], df['close'].astype(float)))


if __name__ == "__main__":
    db = Database()
    db.create_tables()
    print(db.symbol_ranges().to_string())
