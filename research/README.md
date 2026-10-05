# VPVMA Universe Optimization Research Framework

## 🎯 Objective
Find the optimal dynamic universe for VPVMA strategy through rigorous walk-forward testing.

## 📊 Walk-Forward Structure

### Training Windows (5 periods)
1. 2018-01-01 to 2019-12-31 (COVID pre-period)
2. 2019-01-01 to 2020-12-31 (COVID crash + recovery)
3. 2020-01-01 to 2021-12-31 (Recovery + inflation concerns)
4. 2021-01-01 to 2022-12-31 (Fed tightening + bear market)
5. 2022-01-01 to 2023-12-31 (Bear bottom + 2023 rally)

### Validation Period (out-of-sample)
- 2024-01-01 to 2025-11-26 (2024 bull market + current)

## 🔬 Metrics Being Tested
1. **ADX(14)** - Average Directional Index (trend strength) - `adx_metric.py`
2. **MA Alignment** - 20/50/200 moving average trend score (0-3) - `ma_alignment_metric.py`
3. **Price Momentum** - 20-day price change % - `momentum_metric.py`

New metrics subclass `BaseMetric` (`base_metric.py`) and are registered in
`calculate_all_metrics.py` and `research_config.METRICS`.

## 🏗️ File Structure

```
research/
├── research_config.py           # Windows, holdout, paths, selection settings
├── base_metric.py               # Metric base class
├── adx_metric.py / ma_alignment_metric.py / momentum_metric.py
├── calculate_all_metrics.py     # Writes results/metrics/*.csv
├── batch_tester.py              # Walk-forward backtests + holdout run
├── analyze_results.py           # Consistency and holdout summary
└── results/
    ├── metrics/                 # Metric CSVs
    └── backtests/               # training_results.csv, validation_results.csv
```

## 🚀 Usage

### Step 1: Calculate Metrics
```bash
python research/calculate_all_metrics.py
```
Calculates ADX(14), MA alignment (20/50/200) and 20-day momentum for every
qualifying stock.

### Step 2: Walk-Forward Tests
```bash
python research/batch_tester.py --metrics all --sizes 50,100,150,200 --validate
```
Tests each metric × universe size on every training window. The single
configuration with the best MEAN Sharpe across all windows (it must complete
in every window) is then run once on the 2024-2025 holdout.

### Step 3: Analysis
```bash
python research/analyze_results.py
```

## ⚠️ Avoiding Bias

### Look-ahead
- Metrics use only data available at each date
- The universe is selected from metric values on the window's start date

### Survivorship
- Only symbols in the database can be selected; add delisted tickers to
  `symbols.txt` before the historical load to reduce this bias

### Selection
- Configurations are chosen on training windows only (mean Sharpe across windows)
- The holdout is run for that one choice; `--validate-top N` with N > 1 turns the
  holdout into another selection step, and analyze_results.py says so

## 🎯 Success Criteria

A good metric should:
1. ✅ Improve Sharpe ratio vs baseline
2. ✅ Work across multiple windows (consistency)
3. ✅ Maintain or improve win rate
4. ✅ Control drawdown (<25% target)
5. ✅ Validate well on 2024-2025 holdout

## 📝 Notes

- Baseline numbers in research_config.py predate the October 2026 data and
  signal fixes; regenerate them with `python backtest.py --start 2024-01-01`

- Target: Find universe selection that improves to:
  - Sharpe > 1.1
  - CAGR > 14%
  - MaxDD < 23%
  - Consistent across all training windows

- Computational Time:
  - Metric calculation: ~30 min (one-time)
  - Each backtest run: ~2-3 min
  - Total configurations: 8 metrics × 4 sizes × 5 windows = 160 runs
  - Total time: ~6-8 hours
  - Plus validation runs: +2 hours
  - **Total: ~10 hours** (can run overnight)