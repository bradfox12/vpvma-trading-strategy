# VPVMA Trading Strategy

A professional-grade momentum/trend-following trading system based on the Volume-Price Volatility Moving Average (VPVMA) indicator.

## 📊 Overview

This project implements and backtests the VPVMA indicator as a long-only trading strategy across multiple assets. The system has been rigorously tested on 50+ stocks across bull and bear market conditions.

## 🎯 Key Results

### Performance Summary (2020-2025)
- **Tested:** 54 stocks (S&P 500 & NASDAQ)
- **Profitable:** 63% of stocks (34/54)
- **Average Return:** +67% over 5 years
- **Top Performers:** META (+3,594%), NVDA (+654%), PLTR (+465%)

### Bear Market Protection (2022)
- **Beat Buy-and-Hold:** 87.5% of stocks (7/8)
- **Average Alpha:** +62.6% in crash year
- **Drawdown Protection:** Reduced losses by ~12% on average

### Risk-Adjusted Performance
- **Average Sharpe Ratio:** 0.64
- **Best Sharpe:** NVDA (1.22), GE (1.32)
- **Market Exposure:** 49-62% (significant time in cash)

## 🏗️ Project Structure
vpvma_indicator/
├── calculations/          # Core VPVMA calculations
│   ├── price_metrics.py
│   ├── volume_weighted.py
│   ├── exponential_moving.py
│   └── vpvma_core.py
├── signals/              # Trading signal generation
│   └── signal_generator.py
├── data/                 # Database and API integration
│   ├── database.py
│   └── api_client.py
├── scripts/              # Backtesting and analysis tools
│   ├── backtest_vpvma_longonly.py
│   ├── backtest_vpvma_longshort.py
│   ├── batch_backtest.py
│   ├── visualize_vpvma.py
│   └── validate_data.py
├── config.py            # Indicator parameters
├── secure_config.py     # Credential loader (uses .env)
├── main.py             # Main orchestration
└── requirements.txt    # Python dependencies
## 🚀 Quick Start

### 1. Installation
```bash
# Clone the repository
git clone https://github.com/yourusername/vpvma-trading-strategy.git
cd vpvma-trading-strategy

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

### 2. Configuration
bash# Copy example environment file
cp .env.example .env

# Edit .env with your credentials
# - Database connection (PostgreSQL)
# - Polygon.io API key for market data

### 3. Setup Database
bashpython -c "from data.database import Database; db = Database(); db.create_tables()"

###4. Fetch Historical Data
bash# Fetch data for specific symbols (takes ~15-20 minutes for 50 stocks)
python scripts/fetch_and_store.py

###5. Run Backtest
bash# Single symbol backtest
python run_vpvma.py

# Batch backtest all symbols
python scripts/batch_backtest.py

# Visualize signals
python scripts/visualize_vpvma.py
📈 Strategy Overview
VPVMA Indicator
The Volume-Price Volatility Moving Average combines:

Volume-weighted moving averages (short and long-term)
Daily volatility (OHLC standard deviation)
Exponential smoothing
Signal line crossovers with asymmetric thresholds

###Trading Rules (Long-Only)

BUY: When VPVMA crosses above 1.1x signal line (after previous crossover down)
SELL: Exit to cash when VPVMA crosses below 0.8x signal line
Position: 100% allocation when in market, 0% when out

###Key Parameters
pythonWINDOW_FAST = 12   # Short-term period
WINDOW_SLOW = 26   # Long-term period  
WINDOW_SIGN = 9    # Signal line period
BANDWIDTH = 0.1    # Threshold multiplier
🎯 Best Performing Stock Types
Works Best On:

High-volatility growth stocks (tech, semiconductors)
Strong trending markets (up or down)
Momentum names with clear directional moves

Avoid:

Low-volatility defensive stocks (consumer staples)
Sideways/choppy markets
Structurally broken stocks in downtrends

📊 Example Results
Top Performers (2020-2025)
SymbolReturnSharpeMax DDTradesMETA+3,594%0.56-27.9%49NVDA+654%1.22-42.7%75PLTR+465%0.95-54.3%64GE+310%1.32-26.0%82TSLA+150%0.65-55.8%77
2022 Bear Market Test
SymbolStrategyBuy & HoldAlphaNVDA-23.7%-54.1%+30.4%AMZN-13.2%-39.3%+26.1%GOOGL-9.3%-33.6%+24.3%MSFT-5.5%-29.5%+24.1%
⚠️ Important Notes
This is NOT:

A get-rich-quick scheme
A universal strategy that works on all stocks
Set-and-forget automated trading

This IS:

A momentum/trend-following system requiring stock selection
A strategy with proven edge on volatile, trending stocks
A system requiring discipline and emotional control

Risk Warnings:

Past performance does not guarantee future results
Strategy underperforms buy-and-hold in strong bull markets
Requires active monitoring and position management
Designed for risk-adjusted returns, not maximum returns
Works best with curated stock selection (trending names)

🛠️ Development Roadmap

 Core VPVMA indicator implementation
 Long-only backtesting framework
 Long/short backtesting (determined not optimal)
 Multi-symbol batch testing
 Bear market validation (2022)
 Visualization tools
 Dynamic stock selection (trending stocks only)
 Paper trading tracker
 Risk management enhancements
 Live execution framework
 Portfolio optimization

📚 References
Based on academic research on volume-price momentum indicators. Implementation follows rigorous quant methodology with:

Realistic transaction costs (commissions + slippage)
Out-of-sample testing (bear markets)
Multi-regime validation
No parameter optimization (avoiding overfitting)

📝 License
MIT License - See LICENSE file for details
🤝 Contributing
This is a personal trading research project. Feel free to fork and adapt for your own use.
⚡ Disclaimer
This software is for educational and research purposes only. Not financial advice. Trading involves substantial risk of loss. Always do your own research and consult with a qualified financial advisor before making investment decisions.