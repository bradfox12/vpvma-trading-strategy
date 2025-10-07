from data.api_client import MarketDataAPI
from datetime import datetime, timedelta

print("Testing Polygon.io API - HISTORICAL DATA")
print("="*50)

try:
    # Initialize Polygon.io client
    api = MarketDataAPI(provider='polygon')
    
    # Fetch HISTORICAL data (2 years)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=730)  # 2 years
    
    print(f"Fetching AAPL historical data...")
    print(f"Date range: {start_date.date()} to {end_date.date()}")
    print(f"Expected: ~500 trading days\n")
    
    df = api.fetch_ohlcv(
        symbol='AAPL',
        start_date=start_date,
        end_date=end_date,
        interval='1d'
    )
    
    print(f"✓ Successfully fetched {len(df)} records")
    
    # Check if we have enough data for VPVMA
    min_required = 35  # VPVMA warmup period
    if len(df) < min_required:
        print(f"⚠️  Warning: Only {len(df)} records. Need at least {min_required} for VPVMA.")
    elif len(df) < 100:
        print(f"⚠️  Warning: Only {len(df)} records. Recommended: 200+ for meaningful backtesting.")
    else:
        print(f"✓ Sufficient data for VPVMA calculation and backtesting!")
    
    print(f"\nData Summary:")
    print(f"  Start Date: {df['timestamp'].min()}")
    print(f"  End Date: {df['timestamp'].max()}")
    print(f"  Total Days: {len(df)}")
    
    print("\nFirst 3 rows:")
    print(df.head(3))
    
    print("\nLast 3 rows:")
    print(df.tail(3))
    
    print("\n🎉 Polygon.io historical data access working!")
    
except Exception as e:
    print(f"\n✗ Error: {e}")
    print("\n" + "="*50)
    print("TROUBLESHOOTING:")
    print("="*50)
    
    if "403" in str(e) or "Forbidden" in str(e):
        print("❌ API Key Issue:")
        print("  1. Check your MARKET_API_KEY in .env file")
        print("  2. Verify key is active: https://polygon.io/dashboard/api-keys")
        
    elif "429" in str(e):
        print("⏱️  Rate Limit Hit:")
        print("  - Free tier: 5 requests/minute")
        print("  - Wait 60 seconds and try again")
        
    elif "401" in str(e) or "Unauthorized" in str(e):
        print("🔒 Historical Data Access:")
        print("  Your plan may not include full historical data.")
        print("  Check your subscription at: https://polygon.io/pricing")
        print("\n  Polygon Plans:")
        print("  - Starter ($0): 2 years history, 5 req/min")
        print("  - Developer ($29/mo): 2 years history, 100 req/min")
        print("  - Advanced ($99/mo): Full history, unlimited requests")
        
    else:
        print(f"Unexpected error: {e}")
        print("Check your internet connection and API key.")