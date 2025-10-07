"""
Historical Trend Selection
Runs trend selector for each month using ONLY data available at that time
NO LOOK-AHEAD BIAS
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def calculate_trend_score_historical(symbol, db, as_of_date):
    """
    Calculate trend score using only data available before as_of_date
    
    Args:
        symbol: Stock ticker
        db: Database instance
        as_of_date: Date to calculate score (ISO format: '2022-01-01')
    
    Returns:
        dict with trend metrics or None if insufficient data
    """
    try:
        # Get historical data UP TO as_of_date only
        df = db.get_ohlcv_data(symbol)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # CRITICAL: Only use data BEFORE as_of_date
        df = df[df['timestamp'] < as_of_date].copy()
        
        if len(df) < 250:  # Need 250 days for MA200
            return None
        
        # Calculate MAs
        df['ma20'] = df['close'].rolling(20).mean()
        df['ma50'] = df['close'].rolling(50).mean()
        df['ma200'] = df['close'].rolling(200).mean()
        
        # Get most recent values
        current = df.iloc[-1]
        price = current['close']
        ma20 = current['ma20']
        ma50 = current['ma50']
        ma200 = current['ma200']
        
        # 6-month return (125 trading days)
        if len(df) < 125:
            return None
        price_6mo_ago = df.iloc[-126]['close']
        return_6mo = ((price - price_6mo_ago) / price_6mo_ago) * 100
        
        # ATR
        df['high_low'] = df['high'] - df['low']
        atr = df['high_low'].tail(20).mean()
        atr_pct = (atr / price) * 100
        
        # Trend score calculation
        score = 0
        
        # MA alignment (50 points)
        if price > ma200:
            score += 20
        if ma50 > ma200:
            score += 15
        if ma20 > ma50:
            score += 15
        
        # Momentum (30 points)
        if return_6mo > 50:
            score += 30
        elif return_6mo > 25:
            score += 20
        elif return_6mo > 0:
            score += 10
        
        # Volatility (20 points)
        if atr_pct >= 2.5:
            score += 20
        elif atr_pct >= 1.5:
            score += 10
        
        return {
            'symbol': symbol,
            'score': score,
            'price': price,
            'ma20': ma20,
            'ma50': ma50,
            'ma200': ma200,
            'return_6mo': return_6mo,
            'atr_pct': atr_pct,
            'above_ma200': price > ma200,
            'date': as_of_date
        }
        
    except Exception as e:
        return None

def get_historical_universe(db, as_of_date, min_score=75, top_n=12):
    """
    Get top N stocks as of a specific historical date
    
    Args:
        db: Database instance
        as_of_date: Date to run selection (e.g. '2022-01-01')
        min_score: Minimum trend score required
        top_n: Number of stocks to return
    
    Returns:
        list: Stock symbols that qualified
        DataFrame: Full scoring results
    """
    print(f"\n  Selecting universe for {as_of_date}...")
    
    all_symbols = db.list_symbols()
    results = []
    
    for symbol in all_symbols:
        score_data = calculate_trend_score_historical(symbol, db, as_of_date)
        if score_data:
            results.append(score_data)
    
    if len(results) == 0:
        return [], pd.DataFrame()
    
    df = pd.DataFrame(results)
    
    # Filter by minimum score
    df = df[df['score'] >= min_score].copy()
    
    # Sort by score and get top N
    df = df.sort_values('score', ascending=False).head(top_n)
    
    selected = df['symbol'].tolist()
    
    print(f"    Selected {len(selected)} stocks (scores: {df['score'].min()}-{df['score'].max()})")
    
    return selected, df

def get_monthly_universes(db, start_date, end_date, min_score=75, top_n=12):
    """
    Generate universe for each month in date range
    
    Returns:
        dict: {date: [symbols]}
    """
    print("="*80)
    print("GENERATING MONTHLY UNIVERSES (No Look-Ahead)")
    print("="*80)
    
    universes = {}
    
    # Generate first day of each month
    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)
    
    current = start
    while current <= end:
        date_str = current.strftime('%Y-%m-%d')
        symbols, df = get_historical_universe(db, date_str, min_score, top_n)
        universes[date_str] = {
            'symbols': symbols,
            'scores': df
        }
        
        # Next month
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
    
    print(f"\n✓ Generated {len(universes)} monthly universes")
    return universes