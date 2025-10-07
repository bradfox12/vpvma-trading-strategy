import sys
import pandas as pd
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.database import Database

db = Database(db_type='postgresql')
df = db.get_ohlcv_data('SPY')

# Focus on April 9, 2025
april_9 = df[df['timestamp'] == '2025-04-09 04:00:00']

if not april_9.empty:
    row = april_9.iloc[0]
    
    print("="*60)
    print("SPY - APRIL 9, 2025 DATA VERIFICATION")
    print("="*60)
    
    print(f"\nOpen:   ${row['open']:.2f}")
    print(f"High:   ${row['high']:.2f}")
    print(f"Low:    ${row['low']:.2f}")
    print(f"Close:  ${row['close']:.2f}")
    print(f"Volume: {row['volume']:,.0f}")
    
    print(f"\nPrice Range:")
    print(f"  High-Low: ${row['high'] - row['low']:.2f}")
    print(f"  % Range:  {((row['high'] - row['low']) / row['low'] * 100):.2f}%")
    
    if (row['high'] - row['low']) / row['low'] > 0.10:
        print("\n⚠️ 10%+ INTRADAY RANGE - EXTREMELY RARE FOR SPY!")
        print("\nThis could be:")
        print("  1. Real market event (check financial news)")
        print("  2. Data error from Polygon API")
        print("  3. Circuit breaker / trading halt")
        
        print("\n🔍 MANUAL VERIFICATION NEEDED:")
        print("  Check: https://finance.yahoo.com/quote/SPY/history")
        print("  Look for: April 9, 2025")
        print("  Compare: Open, High, Low, Close, Volume")

# Show surrounding days
context = df[(df['timestamp'] >= '2025-04-07') & (df['timestamp'] <= '2025-04-11')]
print(f"\n{'='*60}")
print("APRIL 7-11, 2025 CONTEXT:")
print(f"{'='*60}\n")
print(context[['timestamp', 'open', 'high', 'low', 'close', 'volume']].to_string(index=False))

# Calculate daily returns
context_copy = context.copy()
context_copy['daily_return'] = context_copy['close'].pct_change() * 100

print(f"\n{'='*60}")
print("DAILY RETURNS:")
print(f"{'='*60}")
for idx, row in context_copy.iterrows():
    if pd.notna(row['daily_return']):
        print(f"{row['timestamp'].date()}: {row['daily_return']:+.2f}%")