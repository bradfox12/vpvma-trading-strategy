"""
Calculate All Metrics
=====================
Master script to calculate all metrics for all symbols across full time period

This is Step 1 of the research process.

Usage:
    python calculate_all_metrics.py

Output:
    - Saves metric CSVs to research/results/metrics/
    - Each CSV contains: symbol, timestamp, metric_value
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from datetime import datetime, timedelta
from data.database import Database
from research_config import *

# Import metric calculators
from adx_metric import ADXMetric
from ma_alignment_metric import MAAlignmentMetric
from momentum_metric import MomentumMetric


def get_symbol_universe(db: Database) -> list:
    """
    Get list of all symbols in database (excluding SPY)
    
    Args:
        db: Database instance
    
    Returns:
        List of symbol strings
    """
    print("\n" + "="*70)
    print("QUERYING SYMBOL UNIVERSE")
    print("="*70)
    
    query = """
        SELECT DISTINCT symbol 
        FROM ohlcv_data 
        WHERE symbol != 'SPY'
        ORDER BY symbol
    """
    
    df = pd.read_sql(query, db.engine)
    symbols = df['symbol'].tolist()
    
    print(f"✅ Found {len(symbols)} symbols in database")
    
    # Show sample
    print(f"\nSample symbols: {', '.join(symbols[:10])}")
    if len(symbols) > 10:
        print(f"... and {len(symbols) - 10} more")
    
    return symbols


def apply_minimum_requirements(db: Database, symbols: list) -> list:
    """
    Filter symbols based on minimum requirements
    
    Args:
        db: Database instance
        symbols: List of all symbols
    
    Returns:
        Filtered list of symbols meeting requirements
    """
    print("\n" + "="*70)
    print("APPLYING MINIMUM REQUIREMENTS")
    print("="*70)
    
    print(f"\nRequirements:")
    for key, value in MIN_REQUIREMENTS.items():
        print(f"  {key}: {value}")
    
    print(f"\n⚠️  SURVIVORSHIP BIAS PROTECTION:")
    print(f"  • Checking data across FULL period (2018-2025)")
    print(f"  • Includes delisted/suspended stocks with sufficient history")
    print(f"  • Minimum 200 days of data required (anywhere in period)")
    
    filtered_symbols = []
    
    print(f"\nChecking {len(symbols)} symbols...")
    
    # Track failures for debugging
    no_data_count = 0
    too_few_bars = 0
    price_fail = 0
    volume_fail = 0
    dollar_volume_fail = 0
    errors = []
    
    for i, symbol in enumerate(symbols):
        if (i + 1) % 50 == 0:
            print(f"  Progress: {i+1}/{len(symbols)}", end='\r')
        
        try:
            # SURVIVORSHIP BIAS FIX:
            # Check data across FULL study period (2018-2025), not just recent!
            # This includes delisted stocks that had sufficient trading history
            end_date = datetime(2025, 11, 26)
            start_date = datetime(2018, 1, 1)
            
            df = db.get_ohlcv_data(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date
            )
            
            if df is None:
                no_data_count += 1
                continue
            
            # Require at least 200 days of data across the entire period
            # (Not necessarily recent - could be from 2018-2020 for delisted stocks)
            if len(df) < 200:
                too_few_bars += 1
                continue
            
            # Check requirements
            avg_price = df['close'].mean()
            avg_volume = df['volume'].mean()
            avg_dollar_volume = (df['close'] * df['volume']).mean()
            
            # Track what failed
            passes = True
            
            if avg_price < MIN_REQUIREMENTS['min_price'] or avg_price > MIN_REQUIREMENTS['max_price']:
                price_fail += 1
                passes = False
            
            if avg_volume < MIN_REQUIREMENTS['min_avg_volume']:
                volume_fail += 1
                passes = False
            
            if avg_dollar_volume < MIN_REQUIREMENTS['min_dollar_volume']:
                dollar_volume_fail += 1
                passes = False
            
            if passes:
                filtered_symbols.append(symbol)
        
        except Exception as e:
            errors.append({'symbol': symbol, 'error': str(e)})
            continue
    
    print(f"\n✅ {len(filtered_symbols)}/{len(symbols)} symbols meet requirements")
    print(f"   Filtered out: {len(symbols) - len(filtered_symbols)} symbols")
    
    # Print detailed breakdown
    print(f"\n📊 Filtering breakdown:")
    print(f"   No data returned: {no_data_count}")
    print(f"   Too few bars (<10): {too_few_bars}")
    print(f"   Price out of range: {price_fail}")
    print(f"   Volume too low: {volume_fail}")
    print(f"   Dollar volume too low: {dollar_volume_fail}")
    print(f"   Errors: {len(errors)}")
    
    if errors and len(errors) <= 10:
        print(f"\n⚠️  Sample errors:")
        for err in errors[:5]:
            print(f"   {err['symbol']}: {err['error']}")
    elif len(errors) > 10:
        print(f"\n⚠️  First 10 errors:")
        for err in errors[:10]:
            print(f"   {err['symbol']}: {err['error']}")
    
    # If ALL stocks errored, show unique error types
    if len(errors) == len(symbols):
        print(f"\n❌ CRITICAL: ALL {len(symbols)} stocks threw errors!")
        
        # Group by error message
        error_types = {}
        for err in errors:
            msg = err['error']
            if msg not in error_types:
                error_types[msg] = []
            error_types[msg].append(err['symbol'])
        
        print(f"\n📊 Error breakdown ({len(error_types)} unique error types):")
        for i, (msg, syms) in enumerate(error_types.items(), 1):
            print(f"\n{i}. Error: {msg}")
            print(f"   Affected: {len(syms)} stocks")
            if len(syms) <= 5:
                print(f"   Symbols: {', '.join(syms)}")
            else:
                print(f"   Sample symbols: {', '.join(syms[:5])}...")
    
    if no_data_count == len(symbols):
        print(f"\n❌ ISSUE FOUND: ALL stocks returned no data!")
        print(f"   This means the database query is failing.")
        print(f"   Query range: {start_date.date()} to {end_date.date()}")
        print(f"\n   Possible causes:")
        print(f"   1. Database has no recent data")
        print(f"   2. Timestamp format mismatch")
        print(f"   3. Timezone issue")
    
    elif too_few_bars == len(symbols):
        print(f"\n❌ ISSUE FOUND: ALL stocks have < 200 bars across 2018-2025!")
        print(f"   This suggests database is empty or has very limited data.")
        print(f"   Check: SELECT COUNT(*) FROM ohlcv_data WHERE timestamp >= '2018-01-01'")
    
    return filtered_symbols


def calculate_all_metrics_for_universe(
    db: Database,
    symbols: list,
    start_date: datetime,
    end_date: datetime
):
    """
    Calculate all metrics for all symbols
    
    Args:
        db: Database instance
        symbols: List of symbols to process
        start_date: Start date for calculations
        end_date: End date for calculations
    """
    print("\n" + "="*70)
    print("CALCULATING ALL METRICS")
    print("="*70)
    print(f"\nSymbols: {len(symbols)}")
    print(f"Period: {start_date.date()} to {end_date.date()}")
    print(f"Output directory: {METRICS_DIR}")
    
    # Initialize metric calculators
    metrics = [
        ADXMetric(period=14),
        MAAlignmentMetric(ma_short=20, ma_medium=50, ma_long=200),
        MomentumMetric(period=20),
        # Add more metrics here as you implement them
    ]
    
    print(f"\nMetrics to calculate: {len(metrics)}")
    for metric in metrics:
        print(f"  • {metric.name}: {metric.get_description()}")
    
    # Calculate each metric
    for i, metric in enumerate(metrics, 1):
        print(f"\n{'='*70}")
        print(f"[{i}/{len(metrics)}] CALCULATING: {metric.name}")
        print(f"{'='*70}")
        
        # Calculate for all symbols
        results = metric.calculate_for_universe(
            db=db,
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            batch_size=50
        )
        
        # Save results
        output_file = METRICS_DIR / f"{metric.name.lower().replace('(', '_').replace(')', '').replace(',', '_')}.csv"
        metric.save_results(results, str(output_file))
    
    print(f"\n{'='*70}")
    print("ALL METRICS CALCULATED ✅")
    print(f"{'='*70}")
    print(f"\nResults saved to: {METRICS_DIR}")


def main():
    """
    Main execution
    """
    print("="*70)
    print("VPVMA UNIVERSE OPTIMIZATION - METRIC CALCULATION")
    print("="*70)
    print(f"\nStarted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Initialize database
    db = Database(db_type='postgresql')
    
    # Get symbol universe
    all_symbols = get_symbol_universe(db)
    
    # Apply minimum requirements
    filtered_symbols = apply_minimum_requirements(db, all_symbols)
    
    if len(filtered_symbols) == 0:
        print("\n❌ No symbols meet requirements!")
        return 1
    
    # Calculate metrics for full period (2018-2025)
    # This covers all training windows + validation period
    start_date = datetime(2018, 1, 1)
    end_date = datetime(2025, 11, 26)
    
    calculate_all_metrics_for_universe(
        db=db,
        symbols=filtered_symbols,
        start_date=start_date,
        end_date=end_date
    )
    
    # Summary
    print(f"\n{'='*70}")
    print("CALCULATION COMPLETE")
    print(f"{'='*70}")
    print(f"\nFinished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"\nNext steps:")
    print(f"  1. Review metric CSVs in: {METRICS_DIR}")
    print(f"  2. Run batch testing: python batch_tester.py")
    print(f"  3. Generate reports: python research_report.py")
    
    return 0


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n❌ Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)