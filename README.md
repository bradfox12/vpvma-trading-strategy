# VPVMA: Volume-Price-Volume Moving Average Strategy

Systematic momentum trading system with adaptive risk management.

> **Results below predate the October 2026 fixes** (fully adjusted price history,
> sign-safe signal bands, next-open fills, live/backtest parity) and must be
> re-generated with `python backtest.py` before being relied on.

## Performance Summary

**Long-term validation (2005-2025, 20.8 years):**
- CAGR: 19.08%
- Sharpe Ratio: 1.03
- Sortino Ratio: 1.31
- Calmar Ratio: 0.46
- Maximum Drawdown: -41.48%
- Win Rate: 53.5% (8,033 trades)
- Annual Volatility: 18.71%

**vs SPY Benchmark:**
- Alpha: ~+8-9% annually
- Outperformance: $100K → $3.79M (strategy) vs ~$670K (SPY)

## Research Foundation

Based on Chio (2022): "A comparative study of the MACD-based trading strategies: evidence from the US stock market."

The Volume-Price-Volume Moving Average (VPVMA) indicator incorporates volume and price volatility into traditional MACD calculations. This research implements and extends Chio's framework with institutional-grade risk management.

**Key modifications from original paper:**
1. Independent buy/sell bandwidth controls (paper's coupled bandwidth caused asymmetric exits)
2. Adaptive protection mechanism for bear market regime
3. Screened universe: a volume + fundamentals screen picks up to 500 (typically ~250) US common stocks each quarter (or month); the strategy trades the 15-20 strongest signals within it

## Methodology

### Signal Generation

**Entry signals:**
- VPVMA was at/below VPVMAS and is now above VPVMAS + BUY_BANDWIDTH × |VPVMAS|
- BUY_BANDWIDTH = 0.18 (highly selective)

**Exit signals:**
- VPVMA was at/above VPVMAS and is now below VPVMAS − 2 × SELL_BANDWIDTH × |VPVMAS|
- Base SELL_BANDWIDTH = 0.08
- Adaptive adjustment based on market regime

Using |VPVMAS| keeps the buy band above and the sell band below the signal line
when VPVMAS is negative (about half of all days); the earlier (1 ± bw) × VPVMAS
form inverted both rules on those days.

### Adaptive Risk Management

**Regime detection:** SPY vs 200-day moving average (institutional standard)

**Dynamic exit adjustment:**
- Bull market (SPY > 200MA): SELL_BANDWIDTH = 0.08 → exit at 0.84× signal line
- Bear market (SPY < 200MA): BEAR_SELL_BANDWIDTH = 0.032 → exit at 0.936× signal line

### Validation Protocol

**Phase 1: Walk-forward optimization (2019-2023)**
- Tested 10 protection mechanisms independently
- Identified FastExit+SPY200 as optimal
- 2022 bear market: Sharpe improved from -1.07 to -0.70 (-35% pain reduction)

**Phase 2: Out-of-sample holdout (2024-2025)**
- 183 securities, 471 trading days
- Completely unseen data
- Sharpe: 0.977 → 1.129 (+15.5%)
- CAGR: 12.73% → 14.82%
- Protection active 8.8% of period (appropriately calibrated)

**Phase 3: Extended validation (2005-2025)**
- 20.8 years across multiple complete market cycles
- Includes 2008 financial crisis, 2020 COVID crash, 2022 bear market
- 8,033 trades (statistically robust sample)
- Consistent 53.5% win rate across all regimes

### Transaction Cost Modeling

- Signals at the close, fills at the next open
- Commission: $1 per fill; slippage: 2 basis points per fill
- No look-ahead (tested: changing future prices never changes past decisions)
- Held symbols whose data stops are closed at their last close

## Performance Across Market Regimes

**2008 Financial Crisis:**
- Max drawdown: -41.48% (vs SPY -55%)
- 13% better capital preservation

**2020 COVID Crash:**
- Navigated -34% market drop in 1 month
- Protection mechanism activated appropriately

**2022 Bear Market:**
- Sharpe: -0.70 (protected) vs -1.07 (unprotected)
- 35% reduction in risk-adjusted losses

**Bull Markets (2009-2020, 2023-2024):**
- Full participation maintained
- No performance drag from protection
- Protection inactive 80-90% of time

## Risk Metrics

**Market exposure:**
- Beta: ~0.9-1.1 (similar to market)
- Correlation: ~0.65-0.75 with SPY
- Tracking error: ~8-10% annually

**Drawdown characteristics:**
- Average drawdown: ~-8-12%
- Recovery time: 3-6 months typical
- Maximum underwater period: ~18 months (2008-2009)

**Trade statistics:**
- Average hold period: 35 days
- Average win: $4,419
- Average loss: $-3,192
- Profit factor: 1.38

## Implementation

### Technology Stack
- Python 3.12, NumPy, pandas, SQLAlchemy, PostgreSQL (SQLite for tests)
- Tiingo Power: company list (active + delisted) and split/dividend-adjusted daily prices
- SEC EDGAR (free): point-in-time quarterly fundamentals from XBRL company facts

### Setup and data
```bash
python -m venv venv && venv/bin/pip install -r requirements.txt
cp .env.example .env                        # DB_*, TIINGO_API_KEY, SEC_USER_AGENT
python scripts/phase1_sample.py             # optional: small test of both data sources
python scripts/load_universe.py             # full load (resumable; ~1-2 hours)
python scripts/validate_data.py             # gaps, bad bars, unexplained jumps, stale symbols
python backtest.py --trades-csv trades.csv  # backtest to the latest bar
```
`load_universe.py` writes coverage reports to `logs/` (fundamentals coverage of
tradeable stocks by year, unmatched companies). Companies whose SEC history a
name match cannot find (e.g. Google -> Alphabet) go in `data/cik_overrides.csv`.

### Daily operation
```bash
python run_daily_workflow.py                # after 6 PM ET: data update, then orders for the next session
python daily_portfolio_manager.py --dry-run # preview orders without saving anything
```
- `daily_update.py` refreshes the company list (new listings, ticker changes,
  delistings), appends new bars and re-downloads a stock's history when it pays
  a dividend or splits, and reloads fundamentals for companies that filed a
  10-K/10-Q. It fails - so no orders are generated - if the session's data is incomplete.
- `portfolio_state.json` is the ledger (cash + positions); back it up.
  `trade_tracker.xlsx` and `daily_orders.html` are reports generated from it.
- Logs are in `logs/`. Run `pytest` for the test suite (no database or API keys needed).

### Architecture
```
├── calculations/           # Core VPVMA formulas (Chio 2022)
├── signals/
│   └── signal_generator.py # Entry/exit rules (single source of truth)
├── protection/
│   └── market_regime.py    # SPY 200-day regime (FastExit trigger)
├── data/
│   ├── database.py         # PostgreSQL/SQLite storage (prices, securities, fundamentals)
│   ├── tiingo.py           # Tiingo company list + adjusted prices
│   └── sec_edgar.py        # SEC company facts -> point-in-time quarterly fundamentals
├── scripts/
│   ├── load_universe.py    # Full load of US stocks + coverage report
│   ├── phase1_sample.py    # Small end-to-end data test
│   └── validate_data.py    # Data quality checks
├── strategy.py             # Shared decision engine (backtest + live)
├── backtest.py             # Backtest engine (next-open fills)
├── daily_update.py         # Daily data update
├── daily_portfolio_manager.py # Live order generation + ledger
├── run_daily_workflow.py   # Update + orders, for a scheduler
├── screens.py              # Universe screens (your criteria go here)
├── universe_selector.py    # Live wrapper: runs the screen once per period
├── config.py               # Strategy parameters
├── research/               # Universe-metric walk-forward research
├── tests/                  # pytest suite
└── visualize_results.py    # Performance charts
```

### Key Parameters
```python
WINDOW_FAST = 12          # Short-term EMA period
WINDOW_SLOW = 26          # Long-term EMA period
WINDOW_SIGN = 18          # Signal line SMA period

BUY_BANDWIDTH = 0.18      # Entry selectivity
SELL_BANDWIDTH = 0.08     # Exit threshold (normal)
BEAR_SELL_BANDWIDTH = 0.032  # Exit threshold (bear market)

SPY_MA_PERIOD = 200       # Regime detection window

MAX_POSITIONS = 20        # Hold the strongest signals, up to this many
SWAP_EXIT_RANK = 25       # Rank buffer: a holding is only swapped out once it ranks worse than this
SWAP_CONFIRM_DAYS = 2     # A new signal must rank in the top MAX_POSITIONS on this many consecutive closes
MAX_SWAPS_PER_DAY = None  # Optional cap (None = no cap)

SCREEN_NAME = 'liquidity' # Active screen in screens.SCREENS
SCREEN_FREQUENCY = 'quarterly'
SCREEN_SIZE = 500
```

### Universe screens
A screen runs on the first session of each period using only information public
on that date: prices/volume for the last 400 days, the `securities` table
(type, exchange, sector) and the `fundamentals` table, where every value carries
the date it was filed. Restatements are stored as new versions, so a backtest
never sees a number before it was published. To add criteria, subclass
`Screen` in `screens.py` (see `ExampleFundamentalScreen`), register it in
`SCREENS` and set `SCREEN_NAME`. The backtest and live trading use the same
screen and the same `ScreenData` inputs (a parity test checks this).

## Statistical Validation

**Sample size:** 8,033 trades over 20.8 years
**Universe:** 183 large-cap US equities
**Rebalancing:** Universe re-screened quarterly or monthly (see Universe screens)
**Position sizing:** Equal weight, 5% per position, maximum 20 positions

**Sharpe ratio confidence:**
- 20-year Sharpe: 1.03 ± 0.15 (95% CI)
- Significantly above zero (t-stat > 3.0)
- Top quartile for systematic momentum strategies

**Alpha significance:**
- Annual alpha: +8-9% vs SPY
- Information ratio: ~0.7-0.9
- Statistically significant (p < 0.05)

## Limitations and Considerations

**Strategy limitations:**
1. Momentum strategies underperform during sideways/choppy markets
2. Performance degrades in low-volatility environments
3. Maximum 20 positions limits diversification
4. Monthly rebalancing may miss rapid rotations

**Data considerations:**
1. Survivorship bias partially present (current universe composition)
2. Liquidity assumptions may not hold for smaller allocations
3. Slippage estimates based on normal market conditions

**Implementation challenges:**
1. Requires high-quality daily OHLCV data
2. SPY regime detection needs reliable benchmark data
3. Universe selection process requires fundamental screening

## Future Research

**Potential enhancements:**
1. Multi-regime detection (beyond binary bull/bear)
2. Volatility-adjusted position sizing
3. Sector rotation overlay
4. Machine learning for regime classification

**Areas for investigation:**
1. Optimal rebalancing frequency (monthly vs dynamic)
2. Universe size sensitivity (50 vs 183 vs 500 stocks)
3. Alternative regime indicators (VIX, yield curve, breadth)
4. Transaction cost impact at various capital levels

## References

Chio, P.T. (2022). "A comparative study of the MACD-based trading strategies: evidence from the US stock market." Master's thesis, University of Macau.

Carver, R. (2015). *Systematic Trading: A unique new method for designing trading and investing systems*. Harriman House.

## License

This research implementation is for educational and research purposes. Not financial advice.