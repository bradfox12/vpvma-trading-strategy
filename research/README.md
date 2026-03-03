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

### Tier 1: Trend Quality (Most Robust)
1. **ADX** - Average Directional Index (trend strength)
2. **MA Alignment** - Moving average trend cleanliness (0-3 score)
3. **Price Momentum** - 20-day price change %

### Tier 2: Conviction
4. **Relative Strength** - Performance vs SPY
5. **Volume-Weighted Momentum** - Momentum × volume ratio
6. **Up-Day Volume Ratio** - Buying vs selling pressure

### Tier 3: Volatility Quality
7. **Upside/Downside Vol Ratio** - Healthy vs bearish volatility
8. **ATR Trend** - Volatility expansion/contraction

## 🏗️ File Structure

```
research/
├── README.md                    # This file
├── config.py                    # Research configuration
│
├── metrics/                     # Metric calculators
│   ├── __init__.py
│   ├── adx.py                  # ADX calculation
│   ├── ma_alignment.py         # MA trend score
│   ├── momentum.py             # Price momentum
│   ├── relative_strength.py    # vs SPY
│   ├── volume_weighted.py      # Volume × momentum
│   ├── volume_ratio.py         # Up/down day volume
│   ├── volatility_ratio.py     # Upside/downside vol
│   └── atr_trend.py            # ATR expansion
│
├── universe_selector.py         # Ranks stocks by metrics
├── walk_forward_engine.py       # Manages training windows
├── batch_tester.py              # Runs backtests
├── results_aggregator.py        # Combines results
└── research_report.py           # Generates analysis

results/                         # Output directory
├── metrics/                     # Calculated metric CSVs
├── backtests/                   # Individual backtest results
├── aggregated/                  # Combined analysis
└── reports/                     # HTML/PDF reports
```

## 🚀 Usage

### Step 1: Calculate Metrics (one-time, ~30 min)
```bash
python research/calculate_all_metrics.py
```
This calculates all 8 metrics for all stocks across 2018-2025.

### Step 2: Run Walk-Forward Tests (~4-8 hours)
```bash
python research/batch_tester.py --metrics all --sizes 50,100,150,200
```
Tests each metric × universe size × training window.

### Step 3: Generate Reports
```bash
python research/research_report.py
```
Creates comprehensive analysis comparing all configurations.

## 📈 Expected Outputs

### Metric Comparison Table
| Metric | Avg Sharpe | Avg CAGR | Win Rate | MaxDD | Consistency |
|--------|------------|----------|----------|-------|-------------|
| ADX | 1.15 | 14.2% | 58% | -24% | 4/5 windows |
| MA Alignment | 1.12 | 13.8% | 57% | -26% | 5/5 windows |
| ... | ... | ... | ... | ... | ... |

### Universe Size Analysis
| Size | Avg Sharpe | Avg Trades | Diversification |
|------|------------|------------|-----------------|
| 50 | 1.18 | 1200 | Low |
| 100 | 1.15 | 1800 | Medium |
| 150 | 1.13 | 2200 | High |
| 200 | 1.10 | 2500 | High |

### Window Consistency
Shows which metrics perform well ACROSS ALL windows (robust).

### Validation Period Results
Final test on 2024-2025 holdout data (out-of-sample).

## ⚠️ Avoiding Bias

### No Look-Ahead Bias
- Metrics calculated using only data available at that point
- Universe ranked daily based on trailing data

### No Survivorship Bias
- Includes all stocks in database (even delisted)
- Universe selection happens in real-time (as backtest runs)

### No Selection Bias
- All universe sizes tested
- Results reported for ALL configurations (not just best)

## 🎯 Success Criteria

A good metric should:
1. ✅ Improve Sharpe ratio vs baseline (0.977 baseline)
2. ✅ Work across multiple windows (consistency)
3. ✅ Maintain or improve win rate (56% baseline)
4. ✅ Control drawdown (<25% target)
5. ✅ Validate well on 2024-2025 holdout

## 📝 Notes

- Baseline: Current 183-stock static universe
  - Sharpe: 0.977, CAGR: 12.73%, MaxDD: -23.95%
  - From your validated backtest (2024-2025 holdout)

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