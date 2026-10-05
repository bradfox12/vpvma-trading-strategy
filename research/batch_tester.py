"""
Batch Tester - Walk-Forward Optimization
=========================================
Runs backtest.py with different universe configurations

Walk-forward process:
1. For each training window (2018-2019, 2019-2020, etc.)
2. For each metric (ADX, MA Alignment, Momentum, etc.)
3. For each universe size (50, 100, 150, 200)
4. Select top N stocks by that metric
5. Run backtest on that window
6. Save results

The configuration with the best MEAN Sharpe across all training windows is
then evaluated once on the 2024-2025 holdout.

Usage:
    python batch_tester.py --metrics all --sizes 50,100,150,200
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from data.database import Database
from research_config import *
import json
import argparse


class UniverseSelector:
    """
    Selects universe based on metric values
    """
    
    def __init__(self, metric_csv_path: str):
        """
        Initialize selector with pre-calculated metric
        
        Args:
            metric_csv_path: Path to metric CSV file
        """
        self.metric_name = Path(metric_csv_path).stem
        self.metric_data = pd.read_csv(metric_csv_path)
        print(f"✅ Loaded {self.metric_name}: {len(self.metric_data)} rows, {self.metric_data['symbol'].nunique()} symbols")
    
    def select_universe(
        self,
        date: datetime,
        size: int,
        lookback_days: int = 20
    ) -> list:
        """
        Select top N stocks by metric value on given date
        
        Args:
            date: Date to select universe
            size: Number of stocks to select
            lookback_days: Use average metric over last N days
        
        Returns:
            List of symbol strings
        """
        # Filter to date range (last N days)
        end_date = pd.to_datetime(date)
        start_date = end_date - timedelta(days=lookback_days)
        
        mask = (
            (pd.to_datetime(self.metric_data['timestamp']) >= start_date) &
            (pd.to_datetime(self.metric_data['timestamp']) <= end_date)
        )
        
        recent_data = self.metric_data[mask].copy()
        
        if len(recent_data) == 0:
            return []
        
        # Calculate average metric value per symbol
        avg_metrics = recent_data.groupby('symbol')['metric_value'].mean().reset_index()
        
        # Remove NaN
        avg_metrics = avg_metrics[avg_metrics['metric_value'].notna()]
        
        # Rank by metric (higher is better)
        ranked = avg_metrics.sort_values('metric_value', ascending=False)
        
        # Select top N
        top_symbols = ranked.head(size)['symbol'].tolist()
        
        return top_symbols


class BatchTester:
    """
    Orchestrates batch backtesting with walk-forward optimization
    """
    
    def __init__(self):
        self.db = Database()
        self.results = []
    
    def run_single_backtest(
        self,
        window: dict,
        metric_name: str,
        universe_size: int,
        selected_symbols: list
    ) -> dict:
        """
        Run a single backtest configuration
        
        Args:
            window: Training window dict
            metric_name: Name of metric used for selection
            universe_size: Universe size
            selected_symbols: List of symbols to backtest
        
        Returns:
            Dict with backtest results
        """
        from backtest import run_backtest
        
        # Handle multiple key naming conventions:
        # - Validation: 'start'/'end' 
        # - Training: 'train_start'/'train_end'
        # - Alternative: 'val_start'/'val_end'
        if 'start' in window:
            start_date = window['start']
            end_date = window['end']
        elif 'val_start' in window:
            start_date = window['val_start']
            end_date = window['val_end']
        else:
            start_date = window['train_start']
            end_date = window['train_end']
        
        print(f"\n  Running backtest...")
        print(f"    Symbols: {len(selected_symbols)}")
        print(f"    Period: {start_date} to {end_date}")
        
        try:
            # Run backtest using your existing backtest.py
            results = run_backtest(
                db=self.db,
                symbols=selected_symbols,
                start_date=start_date,
                end_date=end_date,
                initial_capital=INITIAL_CAPITAL
            )
            
            metrics = results.get('metrics', {})
            
            return {
                'window': window['name'],
                'metric': metric_name,
                'universe_size': universe_size,
                'num_symbols': len(selected_symbols),
                'sharpe': metrics.get('sharpe', np.nan),
                'cagr': metrics.get('cagr', np.nan),
                'total_return': metrics.get('total_return', np.nan),
                'win_rate': metrics.get('win_rate', np.nan),
                'max_dd': metrics.get('max_dd', np.nan),
                'sortino': metrics.get('sortino', np.nan),
                'num_trades': len(results.get('trades', [])),
                'status': 'success'
            }
            
        except Exception as e:
            print(f"    ❌ Error: {e}")
            return {
                'window': window['name'],
                'metric': metric_name,
                'universe_size': universe_size,
                'num_symbols': len(selected_symbols),
                'status': 'error',
                'error_message': str(e)
            }
    
    def run_walk_forward_test(
        self,
        metric_csv_path: str,
        universe_sizes: list
    ):
        """
        Run walk-forward test for one metric across all windows and sizes
        
        Args:
            metric_csv_path: Path to metric CSV
            universe_sizes: List of universe sizes to test
        """
        metric_name = Path(metric_csv_path).stem
        
        print(f"\n{'='*70}")
        print(f"WALK-FORWARD TEST: {metric_name}")
        print(f"{'='*70}")
        
        # Load metric
        selector = UniverseSelector(metric_csv_path)
        
        # Test each window
        for window in WALK_FORWARD_WINDOWS:
            print(f"\n📅 Window: {window['name']} ({window['description']})")
            print(f"   Period: {window['train_start']} to {window['train_end']}")
            
            # Test each universe size
            for size in universe_sizes:
                print(f"\n  🔢 Universe size: {size}")
                
                # Select universe at start of window
                window_start = datetime.strptime(window['train_start'], '%Y-%m-%d')
                selected_symbols = selector.select_universe(
                    date=window_start,
                    size=size,
                    lookback_days=20
                )
                
                print(f"    Selected {len(selected_symbols)} symbols")
                
                if len(selected_symbols) == 0:
                    print(f"    ⚠️  No symbols selected, skipping")
                    continue
                
                # Run backtest
                result = self.run_single_backtest(
                    window=window,
                    metric_name=metric_name,
                    universe_size=size,
                    selected_symbols=selected_symbols
                )
                
                # Save result
                self.results.append(result)
                
                # Print summary
                if result['status'] == 'success':
                    print(f"    ✅ Sharpe: {result['sharpe']:.3f}, CAGR: {result['cagr']:.2f}%, Win Rate: {result['win_rate']:.1f}%")
                else:
                    print(f"    ❌ Failed: {result.get('error_message', 'Unknown error')}")
    
    def run_validation_test(
        self,
        best_configs: list
    ):
        """
        Run validation test on 2024-2025 holdout for best configurations
        
        Args:
            best_configs: List of best configuration dicts from training
        """
        print(f"\n{'='*70}")
        print(f"VALIDATION TEST (2024-2025 HOLDOUT)")
        print(f"{'='*70}")
        print(f"\nTesting top {len(best_configs)} configurations on unseen data")
        
        validation_results = []
        
        for i, config in enumerate(best_configs, 1):
            print(f"\n[{i}/{len(best_configs)}] {config['metric']} (size={config['universe_size']})")
            
            # Load metric
            metric_csv = METRICS_DIR / f"{config['metric']}.csv"
            selector = UniverseSelector(str(metric_csv))
            
            # Select universe at start of validation period
            val_start = datetime.strptime(VALIDATION_PERIOD['start'], '%Y-%m-%d')
            selected_symbols = selector.select_universe(
                date=val_start,
                size=config['universe_size'],
                lookback_days=20
            )
            
            print(f"  Selected {len(selected_symbols)} symbols")
            
            if len(selected_symbols) == 0:
                continue
            
            # Run backtest on validation period
            result = self.run_single_backtest(
                window=VALIDATION_PERIOD,
                metric_name=config['metric'],
                universe_size=config['universe_size'],
                selected_symbols=selected_symbols
            )
            
            validation_results.append(result)
            
            if result['status'] == 'success':
                print(f"  ✅ Sharpe: {result['sharpe']:.3f}, CAGR: {result['cagr']:.2f}%")
        
        return validation_results
    
    def save_results(self, output_path: str):
        """
        Save all results to CSV
        
        Args:
            output_path: Path to save results
        """
        df = pd.DataFrame(self.results)
        df.to_csv(output_path, index=False)
        print(f"\n✅ Results saved to: {output_path}")
        print(f"   Total configurations tested: {len(df)}")
    
    def find_best_configs(self, top_n: int = 1) -> list:
        """
        Rank configurations on TRAINING results only.

        A configuration (metric + universe size) is eligible only if it ran
        successfully in every walk-forward window; eligible configurations are
        ranked by mean Sharpe across windows (min Sharpe breaks ties). Picking
        the best single-window result, or picking among several holdout results,
        would overfit and make the holdout no longer out-of-sample.

        Args:
            top_n: Number of configurations to return (default 1 = the pre-registered choice)

        Returns:
            List of dicts with metric, universe_size, sharpe_mean, sharpe_min, cagr_mean,
            win_rate_mean, windows
        """
        df = pd.DataFrame(self.results)
        if df.empty:
            return []
        df = df[df['status'] == 'success']
        n_windows = len(WALK_FORWARD_WINDOWS)

        summary = df.groupby(['metric', 'universe_size']).agg(
            sharpe_mean=('sharpe', 'mean'),
            sharpe_min=('sharpe', 'min'),
            cagr_mean=('cagr', 'mean'),
            win_rate_mean=('win_rate', 'mean'),
            windows=('window', 'nunique'),
        ).reset_index()
        summary = summary[summary['windows'] == n_windows]
        summary = summary.sort_values(['sharpe_mean', 'sharpe_min'], ascending=False)
        return summary.head(top_n).to_dict('records')


def main():
    """
    Main execution
    """
    parser = argparse.ArgumentParser(description='Run batch backtesting')
    parser.add_argument('--metrics', default='all', help='Metrics to test (comma-separated or "all")')
    parser.add_argument('--sizes', default='50,100,150,200', help='Universe sizes (comma-separated)')
    parser.add_argument('--validate', action='store_true', help='Run validation after training')
    parser.add_argument('--validate-only', action='store_true', help='Skip training, only run validation on existing results')
    parser.add_argument('--validate-top', type=int, default=1,
                        help='Holdout-test the top N training configs (default 1). N > 1 turns the '
                             'holdout into another selection step - report it as such.')
    
    args = parser.parse_args()
    
    print("="*70)
    print("VPVMA UNIVERSE OPTIMIZATION - BATCH TESTING")
    print("="*70)
    print(f"\nStarted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Parse universe sizes
    universe_sizes = [int(s) for s in args.sizes.split(',')]
    print(f"\nUniverse sizes to test: {universe_sizes}")
    
    # Initialize tester
    tester = BatchTester()
    
    # VALIDATE-ONLY MODE: Skip training, load existing results
    if args.validate_only:
        print("\n🔍 VALIDATE-ONLY MODE: Skipping training, loading existing results...")
        
        training_results_path = BACKTESTS_DIR / 'training_results.csv'
        
        if not training_results_path.exists():
            print(f"\n❌ ERROR: No training results found at {training_results_path}")
            print("   Run training first: python batch_tester.py --metrics all")
            return 1
        
        # Load existing results
        df = pd.read_csv(training_results_path)
        tester.results = df.to_dict('records')
        
        print(f"✅ Loaded {len(tester.results)} training results")
        
        # Find best configurations
        best_configs = tester.find_best_configs(top_n=args.validate_top)
        
        print(f"\n{'='*70}")
        print(f"TOP CONFIGURATIONS (From Training)")
        print(f"{'='*70}")
        
        for i, config in enumerate(best_configs, 1):
            print(f"{i}. {config['metric']} (size={config['universe_size']})")
            print(f"   Mean Sharpe: {config['sharpe_mean']:.3f} (worst window {config['sharpe_min']:.3f}), "
                  f"mean CAGR: {config['cagr_mean']:.2f}%, mean win rate: {config['win_rate_mean']:.1f}%")
        
        # Run validation
        print(f"\n{'='*70}")
        print("RUNNING VALIDATION ON 2024-2025 HOLDOUT")
        print(f"{'='*70}")
        
        if args.validate_top > 1:
            print(f"\n⚠️  Validating {args.validate_top} configs: choosing among them by holdout "
                  f"results is selection, not out-of-sample validation.")
        validation_results = tester.run_validation_test(best_configs)
        
        # Save validation results
        val_results_path = BACKTESTS_DIR / 'validation_results.csv'
        pd.DataFrame(validation_results).to_csv(val_results_path, index=False)
        print(f"\n✅ Validation results saved to: {val_results_path}")
        
        print(f"\n{'='*70}")
        print("VALIDATION COMPLETE")
        print(f"{'='*70}")
        print(f"\nFinished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        return 0
    
    # NORMAL MODE: Run training
    # Get metric CSVs
    if args.metrics == 'all':
        metric_files = list(METRICS_DIR.glob('*.csv'))
    else:
        metric_names = args.metrics.split(',')
        metric_files = [METRICS_DIR / f"{name.strip()}.csv" for name in metric_names]
    
    print(f"Metrics to test: {len(metric_files)}")
    for mf in metric_files:
        print(f"  • {mf.stem}")
    
    # Run walk-forward tests
    for metric_file in metric_files:
        tester.run_walk_forward_test(
            metric_csv_path=str(metric_file),
            universe_sizes=universe_sizes
        )
    
    # Save training results
    training_results_path = BACKTESTS_DIR / 'training_results.csv'
    tester.save_results(str(training_results_path))
    
    # Find best configurations
    best_configs = tester.find_best_configs(top_n=args.validate_top)
    
    print(f"\n{'='*70}")
    print(f"TOP CONFIGURATIONS (Training)")
    print(f"{'='*70}")
    
    for i, config in enumerate(best_configs, 1):
        print(f"{i}. {config['metric']} (size={config['universe_size']})")
        print(f"   Mean Sharpe: {config['sharpe_mean']:.3f} (worst window {config['sharpe_min']:.3f}), "
              f"mean CAGR: {config['cagr_mean']:.2f}%, mean win rate: {config['win_rate_mean']:.1f}%")
    
    # Run validation if requested
    if args.validate and best_configs:
        validation_results = tester.run_validation_test(best_configs)
        
        # Save validation results
        val_results_path = BACKTESTS_DIR / 'validation_results.csv'
        pd.DataFrame(validation_results).to_csv(val_results_path, index=False)
        print(f"\n✅ Validation results saved to: {val_results_path}")
    
    print(f"\n{'='*70}")
    print("BATCH TESTING COMPLETE")
    print(f"{'='*70}")
    print(f"\nFinished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
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