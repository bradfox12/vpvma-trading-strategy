#!/usr/bin/env python3
"""
Daily Workflow Runner
=====================
1. daily_update.py            - fetch the latest close into the database
2. daily_portfolio_manager.py - generate orders for the next session

The portfolio manager only runs if the data update succeeded, so orders are
never generated from stale data. Both steps log to logs/; this runner logs to
logs/daily_workflow.log. Exit code is non-zero if either step fails, so a
scheduler (cron / Task Scheduler) can alert on failure.

Usage:
    python run_daily_workflow.py [--dry-run]

Schedule (Mon-Fri after 4:30 PM ET), e.g. cron:
    30 16 * * 1-5 cd /path/to/vpvma-trading-strategy && venv/bin/python run_daily_workflow.py
"""

import argparse
import subprocess
import sys
from pathlib import Path

from logging_setup import setup_logging

PROJECT_ROOT = Path(__file__).resolve().parent


def run_step(logger, name, args, timeout):
    logger.info("Running %s ...", name)
    try:
        result = subprocess.run([sys.executable, *args], cwd=PROJECT_ROOT, timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.error("%s timed out after %ds", name, timeout)
        return False
    if result.returncode != 0:
        logger.error("%s failed with exit code %d - see logs/", name, result.returncode)
        return False
    logger.info("%s complete", name)
    return True


def main():
    parser = argparse.ArgumentParser(description='Run the daily data update and portfolio manager')
    parser.add_argument('--dry-run', action='store_true', help='Pass --dry-run to the portfolio manager')
    args = parser.parse_args()

    logger = setup_logging('daily_workflow')
    logger.info("=" * 80)
    logger.info("VPVMA DAILY WORKFLOW")
    logger.info("=" * 80)

    if not run_step(logger, 'daily_update.py', ['daily_update.py'], timeout=1800):
        logger.error("Data update failed - NOT generating orders from stale data")
        return 1

    pm_args = ['daily_portfolio_manager.py'] + (['--dry-run'] if args.dry_run else [])
    if not run_step(logger, 'daily_portfolio_manager.py', pm_args, timeout=1800):
        return 1

    logger.info("Workflow complete - review daily_orders.html and place orders before the next open")
    return 0


if __name__ == "__main__":
    sys.exit(main())
