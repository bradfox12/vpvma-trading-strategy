#!/usr/bin/env python3
"""
Smart Daily Workflow Runner
============================
Handles weekends and holidays automatically
Gets the most recent trading data and generates appropriate signals

Usage:
    python run_daily_workflow_smart.py
    
Schedule:
    - Weekdays after 4:30 PM ET: Gets today's data, signals for tomorrow
    - Weekends: Gets Friday's data, signals for Monday
    - Holidays: Automatically detects and uses last trading day
"""

import subprocess
import sys
from datetime import datetime, timedelta
import pandas as pd


def get_workflow_dates():
    """
    Determine correct dates for workflow based on current day/time
    """
    now = datetime.now()
    today = pd.Timestamp.now().normalize()
    
    # Determine last trading day and signal target
    if today.weekday() == 0:  # Monday
        last_trading = today - timedelta(days=3)  # Friday
        signal_for = today
        
    elif today.weekday() == 6:  # Sunday
        last_trading = today - timedelta(days=2)  # Friday
        signal_for = today + timedelta(days=1)  # Monday
        
    elif today.weekday() == 5:  # Saturday
        last_trading = today - timedelta(days=1)  # Friday
        signal_for = today + timedelta(days=2)  # Monday
        
    else:  # Tuesday-Friday
        if now.hour >= 16:  # After 4 PM
            last_trading = today
            signal_for = today + timedelta(days=1)
            # Skip weekend if Friday
            if signal_for.weekday() >= 5:
                signal_for = today + timedelta(days=3)
        else:  # Before 4 PM
            last_trading = today - timedelta(days=1)
            signal_for = today
    
    return last_trading, signal_for


def main():
    """
    Run the complete daily workflow with smart date handling
    """
    print("="*80)
    print("VPVMA SMART DAILY WORKFLOW")
    print("="*80)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Day: {datetime.now().strftime('%A')}")
    print("="*80)
    
    # Get appropriate dates
    last_trading, signal_for = get_workflow_dates()
    
    print(f"\n📅 Date Configuration:")
    print(f"   Last trading day: {last_trading.strftime('%Y-%m-%d (%A)')}")
    print(f"   Generate signals for: {signal_for.strftime('%Y-%m-%d (%A)')}")
    print("="*80)
    
    # Step 1: Update market data
    print("\n[1/2] Updating market data...")
    print(f"      Getting data through: {last_trading.strftime('%Y-%m-%d')}")
    
    # Try the fixed update script first
    try:
        result = subprocess.run(
            [sys.executable, "daily_update_fixed.py"],
            capture_output=True,
            text=True,
            timeout=600  # 10 minute timeout
        )
        
        if result.returncode == 0:
            print("✅ Data update complete")
            # Show key output lines
            for line in result.stdout.split('\n'):
                if any(keyword in line for keyword in ['Updated:', 'current:', 'Database now']):
                    print(f"   {line.strip()}")
        else:
            print("⚠️ Fixed update had issues, trying original...")
            # Fallback to original update
            result = subprocess.run([sys.executable, "daily_update.py"], capture_output=False)
            if result.returncode != 0:
                print("\n❌ Data update failed!")
                print("   Check daily_update.log for details")
                sys.exit(1)
    
    except subprocess.TimeoutExpired:
        print("⚠️ Update taking too long (>10 min), continuing anyway...")
    except FileNotFoundError:
        print("⚠️ daily_update_fixed.py not found, using original...")
        result = subprocess.run([sys.executable, "daily_update.py"], capture_output=False)
        if result.returncode != 0:
            print("\n❌ Data update failed!")
            sys.exit(1)
    
    # Step 2: Portfolio management
    print(f"\n[2/2] Running portfolio manager...")
    print(f"      Generating orders for: {signal_for.strftime('%Y-%m-%d')}")
    
    try:
        result = subprocess.run(
            [sys.executable, "daily_portfolio_manager.py"],
            capture_output=False,
            timeout=300  # 5 minute timeout
        )
        
        if result.returncode != 0:
            print("\n⚠️ Portfolio management had warnings")
            print("   Check outputs manually")
        else:
            print("✅ Portfolio management complete")
            
    except subprocess.TimeoutExpired:
        print("⚠️ Portfolio manager timeout - check if it's still running")
    except FileNotFoundError:
        print("❌ daily_portfolio_manager.py not found!")
        sys.exit(1)
    
    # Summary
    print("\n" + "="*80)
    print("WORKFLOW COMPLETE")
    print("="*80)
    print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Day-specific instructions
    if signal_for.weekday() == 0 and datetime.now().weekday() in [5, 6]:
        print("\n📌 WEEKEND INSTRUCTIONS:")
        print(f"   Orders generated for Monday {signal_for.strftime('%Y-%m-%d')}")
        print("   Place orders Sunday evening or Monday pre-market")
    else:
        print(f"\n📌 NEXT STEPS:")
        print(f"   1. Review orders for {signal_for.strftime('%Y-%m-%d')}")
        print("   2. Check email for trading orders")
        print("   3. Review daily_orders.html")
        print("   4. Check trade_tracker.xlsx")
        print(f"   5. Place orders before {signal_for.strftime('%Y-%m-%d')} 9:30 AM ET")
    
    print("="*80)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nWorkflow interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Workflow error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)