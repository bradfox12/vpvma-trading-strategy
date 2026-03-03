from data.database import Database
import pandas as pd

db = Database(db_type='postgresql')

# Check total stocks
query1 = "SELECT COUNT(DISTINCT symbol) as total FROM ohlcv_data"
total = pd.read_sql(query1, db.engine)
print(f"Total symbols: {total['total'].iloc[0]}")

# Check most recent date
query2 = "SELECT MAX(timestamp) as latest FROM ohlcv_data"
latest = pd.read_sql(query2, db.engine)
print(f"Most recent date: {latest['latest'].iloc[0]}")

# Check symbols with recent data
query3 = """
    SELECT symbol, MAX(timestamp) as latest 
    FROM ohlcv_data 
    GROUP BY symbol 
    ORDER BY MAX(timestamp) DESC 
    LIMIT 20
"""
recent = pd.read_sql(query3, db.engine)
print("\nTop 20 symbols by latest date:")
print(recent)