"""
Database connection and operations
Supports PostgreSQL, MySQL, and SQLite
"""

import pandas as pd
import numpy as np
from typing import Optional, List, Tuple
from datetime import datetime
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager
from secure_config import SecureConfig


class Database:
    """
    Database handler for storing and retrieving OHLCV data
    """
    
    def __init__(self, db_type: str = 'postgresql'):
        """
        Initialize database connection
        
        Args:
            db_type: Database type ('postgresql', 'mysql', 'sqlite')
        """
        self.db_type = db_type
        self.connection_url = SecureConfig.get_database_url(db_type)
        self.engine = create_engine(self.connection_url, echo=False)
        self.SessionLocal = sessionmaker(bind=self.engine)
    
    @contextmanager
    def get_session(self):
        """Context manager for database sessions"""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()
    
    def create_tables(self):
        """
        Create OHLCV table if it doesn't exist
        """
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS ohlcv_data (
            id SERIAL PRIMARY KEY,
            symbol VARCHAR(20) NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            open DECIMAL(18, 8) NOT NULL,
            high DECIMAL(18, 8) NOT NULL,
            low DECIMAL(18, 8) NOT NULL,
            close DECIMAL(18, 8) NOT NULL,
            volume BIGINT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(symbol, timestamp)
        );
        
        CREATE INDEX IF NOT EXISTS idx_symbol_timestamp 
        ON ohlcv_data(symbol, timestamp);
        """
        
        with self.engine.connect() as conn:
            conn.execute(text(create_table_sql))
            conn.commit()
        
        print("✓ Tables created successfully")
    
    def insert_ohlcv_data(
        self,
        symbol: str,
        df: pd.DataFrame,
        replace: bool = False
    ):
        """
        Insert OHLCV data into database
        
        Args:
            symbol: Stock/crypto symbol
            df: DataFrame with columns [timestamp, open, high, low, close, volume]
            replace: If True, delete existing data for symbol first
        """
        # Validate DataFrame has required columns
        required_cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        if not all(col in df.columns for col in required_cols):
            raise ValueError(f"DataFrame must contain columns: {required_cols}")
        
        # Add symbol column
        df = df.copy()
        df['symbol'] = symbol
        
        # Delete existing data if replace=True
        if replace:
            with self.engine.connect() as conn:
                conn.execute(
                    text("DELETE FROM ohlcv_data WHERE symbol = :symbol"),
                    {"symbol": symbol}
                )
                conn.commit()
        
        # Insert data
        df.to_sql(
            'ohlcv_data',
            self.engine,
            if_exists='append',
            index=False,
            method='multi'
        )
        
        print(f"✓ Inserted {len(df)} records for {symbol}")
    
    def get_ohlcv_data(
        self,
        symbol: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Retrieve OHLCV data from database
    
        Args:
            symbol: Stock/crypto symbol
            start_date: Optional start date filter
            end_date: Optional end date filter
            limit: Optional limit on number of records
    
        Returns:
            DataFrame with OHLCV data sorted chronologically
        """
        query = """
        SELECT timestamp, open, high, low, close, volume
        FROM ohlcv_data
        WHERE symbol = %(symbol)s
        """
    
        params = {"symbol": symbol}
    
        if start_date:
            query += " AND timestamp >= %(start_date)s"
            params["start_date"] = start_date
    
        if end_date:
            query += " AND timestamp <= %(end_date)s"
            params["end_date"] = end_date
    
        query += " ORDER BY timestamp ASC"
    
        if limit:
            query += f" LIMIT {limit}"
    
        df = pd.read_sql(query, self.engine, params=params)
    
        return df
    
    def get_ohlcv_arrays(
        self,
        symbol: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Get OHLCV data as numpy arrays (ready for VPVMA calculation)
        
        Args:
            symbol: Stock/crypto symbol
            start_date: Optional start date filter
            end_date: Optional end date filter
        
        Returns:
            Tuple of (open, high, low, close, volume) as numpy arrays
        """
        df = self.get_ohlcv_data(symbol, start_date, end_date)
        
        if df.empty:
            raise ValueError(f"No data found for symbol: {symbol}")
        
        return (
            df['open'].to_numpy(),
            df['high'].to_numpy(),
            df['low'].to_numpy(),
            df['close'].to_numpy(),
            df['volume'].to_numpy()
        )
    
    def list_symbols(self) -> List[str]:
        """
        Get list of all symbols in database
        
        Returns:
            List of unique symbols
        """
        query = "SELECT DISTINCT symbol FROM ohlcv_data ORDER BY symbol"
        df = pd.read_sql(query, self.engine)
        return df['symbol'].tolist()
    
    def get_data_info(self, symbol: str) -> dict:
        """
        Get information about data availability for a symbol
    
        Returns:
            Dictionary with date range and record count
        """
        query = """
        SELECT 
            COUNT(*) as record_count,
            MIN(timestamp) as start_date,
            MAX(timestamp) as end_date
        FROM ohlcv_data
        WHERE symbol = %(symbol)s
        """
    
        df = pd.read_sql(query, self.engine, params={"symbol": symbol})
    
        return {
            'symbol': symbol,
            'record_count': int(df['record_count'].iloc[0]),
            'start_date': df['start_date'].iloc[0],
            'end_date': df['end_date'].iloc[0]
        }


# Example usage
if __name__ == "__main__":
    # Initialize database
    db = Database(db_type='postgresql')
    
    # Create tables
    db.create_tables()
    
    # List available symbols
    symbols = db.list_symbols()
    print(f"Available symbols: {symbols}")