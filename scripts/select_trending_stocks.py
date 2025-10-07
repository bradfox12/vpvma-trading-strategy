import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.database import Database
import pandas as pd
import numpy as np
from datetime import datetime

print("="*80)
print("TRENDING STOCKS SELECTOR - DYNAMIC VPVMA UNIVERSE")
print("="*80)

db = Database(db_type='postgresql')
all_symbols = db.list_symbols()

print(f"\nAnalyzing {len(all_symbols)} symbols for trend strength...")
print(f"Analysis Date: {datetime.now().strftime('%Y-%m-%d')}")
print("="*80)

results = []

for idx, symbol in enumerate(all_symbols, 1):
    print(f"\r[{idx}/{len(all_symbols)}] Analyzing {symbol:6}...", end='', flush=True)
    
    try:
        df = db.get_ohlcv_data(symbol)
        
        if len(df) < 252:  # Need at least 1 year
            continue
        
        # Calculate moving averages
        df['ma_20'] = df['close'].rolling(20).mean()
        df['ma_50'] = df['close'].rolling(50).mean()
        df['ma_200'] = df['close'].rolling(200).mean()
        
        # Get latest values
        latest = df.iloc[-1]
        latest_price = latest['close']
        latest_ma20 = latest['ma_20']
        latest_ma50 = latest['ma_50']
        latest_ma200 = latest['ma_200']
        
        # Skip if MAs not available
        if pd.isna(latest_ma200):
            continue
        
        # Calculate returns
        ret_1m = ((df['close'].iloc[-1] / df['close'].iloc[-21]) - 1) * 100 if len(df) >= 21 else 0
        ret_3m = ((df['close'].iloc[-1] / df['close'].iloc[-63]) - 1) * 100 if len(df) >= 63 else 0
        ret_6m = ((df['close'].iloc[-1] / df['close'].iloc[-126]) - 1) * 100 if len(df) >= 126 else 0
        ret_1y = ((df['close'].iloc[-1] / df['close'].iloc[-252]) - 1) * 100 if len(df) >= 252 else 0
        
        # Calculate volatility (ATR as % of price)
        df['high_low'] = df['high'] - df['low']
        df['high_close'] = abs(df['high'] - df['close'].shift())
        df['low_close'] = abs(df['low'] - df['close'].shift())
        df['tr'] = df[['high_low', 'high_close', 'low_close']].max(axis=1)
        atr_14 = df['tr'].rolling(14).mean().iloc[-1]
        atr_pct = (atr_14 / latest_price) * 100
        
        # Average volume (last 20 days)
        avg_volume = df['volume'].tail(20).mean()
        
        # Trend strength checks
        above_ma20 = latest_price > latest_ma20
        above_ma50 = latest_price > latest_ma50
        above_ma200 = latest_price > latest_ma200
        ma50_above_ma200 = latest_ma50 > latest_ma200  # Golden cross
        ma20_above_ma50 = latest_ma20 > latest_ma50
        
        # MA slopes (is trend strengthening?)
        if len(df) >= 220:
            ma200_slope = ((latest_ma200 - df['ma_200'].iloc[-20]) / df['ma_200'].iloc[-20]) * 100
        else:
            ma200_slope = 0
            
        if len(df) >= 70:
            ma50_slope = ((latest_ma50 - df['ma_50'].iloc[-20]) / df['ma_50'].iloc[-20]) * 100
        else:
            ma50_slope = 0
        
        # Distance from MAs
        distance_from_ma50 = ((latest_price - latest_ma50) / latest_ma50) * 100
        distance_from_ma200 = ((latest_price - latest_ma200) / latest_ma200) * 100
        
        # Trend score (0-100)
        trend_score = 0
        
        # Position relative to MAs (40 points max)
        if above_ma200:
            trend_score += 20
        if above_ma50:
            trend_score += 10
        if above_ma20:
            trend_score += 10
        
        # MA alignment (20 points max)
        if ma50_above_ma200:
            trend_score += 10
        if ma20_above_ma50:
            trend_score += 10
        
        # Momentum (25 points max)
        if ret_6m > 50:
            trend_score += 15
        elif ret_6m > 20:
            trend_score += 10
        elif ret_6m > 0:
            trend_score += 5
        
        if ret_1m > 0:
            trend_score += 5
        if ret_3m > 0:
            trend_score += 5
        
        # MA slopes (15 points max)
        if ma200_slope > 0:
            trend_score += 10
        if ma50_slope > 0:
            trend_score += 5
        
        # Momentum classification
        if ret_6m > 50:
            momentum = "EXPLOSIVE"
        elif ret_6m > 30:
            momentum = "STRONG"
        elif ret_6m > 10:
            momentum = "GOOD"
        elif ret_6m > 0:
            momentum = "WEAK"
        elif ret_6m > -20:
            momentum = "NEGATIVE"
        else:
            momentum = "CRASH"
        
        # Trend status
        if above_ma50 and above_ma200 and ma50_above_ma200:
            trend_status = "STRONG_UPTREND"
        elif above_ma200 and above_ma50:
            trend_status = "UPTREND"
        elif above_ma200:
            trend_status = "WEAK_UPTREND"
        elif above_ma50:
            trend_status = "SHORT_TERM_UP"
        else:
            trend_status = "DOWNTREND"
        
        # Volatility category
        if atr_pct > 5:
            vol_category = "HIGH"
        elif atr_pct > 3:
            vol_category = "MEDIUM"
        else:
            vol_category = "LOW"
        
        results.append({
            'Symbol': symbol,
            'Price': latest_price,
            'MA20': latest_ma20,
            'MA50': latest_ma50,
            'MA200': latest_ma200,
            'Ret_1M_%': ret_1m,
            'Ret_3M_%': ret_3m,
            'Ret_6M_%': ret_6m,
            'Ret_1Y_%': ret_1y,
            'ATR_%': atr_pct,
            'Avg_Volume': avg_volume,
            'Dist_MA50_%': distance_from_ma50,
            'Dist_MA200_%': distance_from_ma200,
            'MA50_Slope_%': ma50_slope,
            'MA200_Slope_%': ma200_slope,
            'Trend_Score': trend_score,
            'Trend_Status': trend_status,
            'Momentum': momentum,
            'Volatility': vol_category,
            'Above_MA20': above_ma20,
            'Above_MA50': above_ma50,
            'Above_MA200': above_ma200,
            'Golden_Cross': ma50_above_ma200
        })
        
    except Exception as e:
        continue

print("\r" + " " * 80 + "\r", end='')  # Clear line

# Results DataFrame
results_df = pd.DataFrame(results)

if len(results_df) == 0:
    print("\n❌ No stocks could be analyzed!")
    exit(1)

results_df = results_df.sort_values('Trend_Score', ascending=False)

print("\n" + "="*80)
print("STOCK SCREENING RESULTS")
print("="*80)

# Category breakdown
strong_uptrend = results_df[results_df['Trend_Status'] == 'STRONG_UPTREND']
any_uptrend = results_df[results_df['Trend_Status'].isin(['STRONG_UPTREND', 'UPTREND', 'WEAK_UPTREND'])]
downtrend = results_df[results_df['Trend_Status'] == 'DOWNTREND']

print(f"\nTotal Analyzed: {len(results_df)}")
print(f"Strong Uptrend: {len(strong_uptrend)} ({len(strong_uptrend)/len(results_df)*100:.1f}%)")
print(f"Any Uptrend: {len(any_uptrend)} ({len(any_uptrend)/len(results_df)*100:.1f}%)")
print(f"Downtrend: {len(downtrend)} ({len(downtrend)/len(results_df)*100:.1f}%)")

# Momentum distribution
print("\nMomentum Distribution:")
for momentum_type in ['EXPLOSIVE', 'STRONG', 'GOOD', 'WEAK', 'NEGATIVE', 'CRASH']:
    count = len(results_df[results_df['Momentum'] == momentum_type])
    if count > 0:
        print(f"  {momentum_type:12}: {count:3} stocks")

# Quality filters - Top candidates for VPVMA
print("\n" + "="*80)
print("TOP 25 VPVMA CANDIDATES (By Trend Score)")
print("="*80)

top_25 = results_df.head(25)

print("\n{:<8} {:<18} {:>8} {:>8} {:>8} {:<12} {:<8}".format(
    "Symbol", "Trend Status", "Score", "6M Ret%", "1Y Ret%", "Momentum", "ATR%"
))
print("-" * 80)

for idx, row in top_25.iterrows():
    print("{:<8} {:<18} {:>8.0f} {:>8.1f} {:>8.1f} {:<12} {:>6.2f}".format(
        row['Symbol'],
        row['Trend_Status'],
        row['Trend_Score'],
        row['Ret_6M_%'],
        row['Ret_1Y_%'],
        row['Momentum'],
        row['ATR_%']
    ))

# High-quality filter (optimal for VPVMA)
print("\n" + "="*80)
print("HIGH-QUALITY TRENDING STOCKS (Optimal for VPVMA)")
print("="*80)

high_quality = results_df[
    (results_df['Trend_Score'] >= 75) &  # Strong trend
    (results_df['Above_MA200'] == True) &  # Above long-term MA
    (results_df['Ret_6M_%'] > 0) &  # Positive momentum
    (results_df['ATR_%'] >= 2.5)  # Sufficient volatility for signals
].head(30)

print(f"\n✅ {len(high_quality)} HIGH-QUALITY CANDIDATES FOUND")

if len(high_quality) > 0:
    print("\n{:<8} {:>8} {:>9} {:>9} {:>9} {:<10}".format(
        "Symbol", "Score", "6M Ret%", "1Y Ret%", "ATR%", "Status"
    ))
    print("-" * 60)
    
    for idx, row in high_quality.iterrows():
        print("{:<8} {:>8.0f} {:>9.1f} {:>9.1f} {:>9.2f} {:<10}".format(
            row['Symbol'],
            row['Trend_Score'],
            row['Ret_6M_%'],
            row['Ret_1Y_%'],
            row['ATR_%'],
            row['Trend_Status'][:10]
        ))

# Export files
timestamp = datetime.now().strftime('%Y%m%d')
filename_all = f"stock_trend_analysis_{timestamp}.csv"
filename_top25 = f"vpvma_top25_trending_{timestamp}.csv"
filename_high_quality = f"vpvma_high_quality_{timestamp}.csv"

results_df.to_csv(filename_all, index=False)
top_25.to_csv(filename_top25, index=False)
high_quality.to_csv(filename_high_quality, index=False)

print(f"\n✓ Full analysis: {filename_all}")
print(f"✓ Top 25 trending: {filename_top25}")
print(f"✓ High quality candidates: {filename_high_quality}")

# Recommendations
print("\n" + "="*80)
print("ACTIONABLE RECOMMENDATIONS")
print("="*80)

print("\n📊 FOR VPVMA TRADING:")
print("  ✓ Focus on HIGH-QUALITY list above")
print("  ✓ Minimum criteria:")
print("    - Trend Score > 75")
print("    - Above 200-day MA")
print("    - Positive 6-month momentum")
print("    - ATR > 2.5% (volatility for signals)")

if len(high_quality) > 0:
    print(f"\n🎯 SUGGESTED PORTFOLIO:")
    print(f"  • Trade top {min(20, len(high_quality))} from high-quality list")
    print(f"  • Equal weight: {100/min(20, len(high_quality)):.1f}% per stock")
    print(f"  • Review frequency: Monthly or Quarterly")
    print(f"  • Rebalance when stocks drop below criteria")

print("\n⚠️  STOCKS TO AVOID:")
avoid = results_df[
    (results_df['Trend_Score'] < 50) |
    (results_df['Above_MA200'] == False) |
    (results_df['Ret_6M_%'] < -10)
]
print(f"  • {len(avoid)} stocks with weak/negative trends")
if len(avoid) > 0:
    print(f"  • Examples: {', '.join(avoid.head(10)['Symbol'].tolist())}")

print("\n📅 NEXT STEPS:")
print("  1. Run backtest on high-quality list")
print("     → python scripts/batch_backtest.py (filter to high-quality symbols)")
print("  2. Paper trade for 1-3 months")
print("  3. Review and update list monthly")
print("  4. Go live with real capital")

print("\n" + "="*80)
print("TREND ANALYSIS COMPLETE")
print("="*80)