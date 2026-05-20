# Stock Quant System

An AI agent pipeline that generates, reviews, and backtests quantitative trading strategies for any US stock ticker. Type a ticker, watch four specialized agents collaborate, and get a full strategy with source code, performance charts, and an LLM-written analysis — all in the browser.

---

## Quick Start

```bash
# 1. Clone and install
git clone <repo>
cd agent_stock_system
uv sync                          # installs all deps with Python 3.12

# 2. Set your API key
echo "OPENAI_API_KEY=sk-..." >> .env

# 3. Run
uv run uvicorn src.main:app --reload --port 9000


uv run uvicorn src.main:app --reload --reload-dir src --reload-dir frontend --port 9000





# 4. Open
open http://localhost:9000
```

Enter a ticker (e.g. `NVDA`, `AAPL`, `TSLA`) and click **Analyze**. The full pipeline takes 30–90 seconds.

**Requirements:** Python 3.12, a valid OpenAI API key. No other infrastructure needed.

---

## Key Features

| Feature | Detail |
|---|---|
| Strategy generation | GPT-4o writes a complete `backtesting.py` strategy class tailored to current market conditions |
| Code review & repair | PythonMasterAgent runs static checks (AST-level) and self-heals issues before execution — up to 3 repair iterations |
| Real backtest execution | Strategy code runs against 2 years of real OHLCV data via `backtesting.py` |
| Re-run without regenerating | Click **▶ Run Again** on any saved strategy to re-backtest with fresh data — no LLM call needed |
| Live progress stream | Each agent stage streams via SSE — no page refreshes |
| Visualization | Equity curve vs buy-and-hold, drawdown chart, per-trade P&L bars, trade log table |
| LLM narrative | GPT-4o writes a 3-paragraph post-backtest analysis: performance, risk, tuning suggestions |
| Persistent history | All strategies and runs saved to SQLite — click any past run to reload its charts |

---

## Architecture

```
Browser (HTML + JS)
  │  SSE stream (live agent progress)
  │  REST (load results, history)
  ▼
FastAPI server (src/main.py)
  │
  ▼
CrewAI pipeline  ──────────────────────────────────────────────────┐
  │                                                                │
  ▼                                                                │
MarketDataAgent          StrategyAgent           PythonMasterAgent  BacktestAgent
  │                          │                        │                │
  │ fetch_ohlcv()            │ GPT-4o generates       │ AST checks     │ exec() strategy
  │ compute_indicators()     │ Strategy subclass       │ + LLM repair   │ backtesting.py
  │ market_summary()         │ + explanation           │ loop (≤3x)     │ metrics + narrative
  │                          │                        │                │
  └──────────────────────────┴────────────────────────┴────────────────┘
                                         │
                                    SQLite DB
                              strategies · code_reviews
                                  backtest_runs
```

**Flow is strictly sequential:** each agent receives the previous agent's output before starting. Progress events are emitted after each stage.

---

## Agent Pipeline

### 1 — MarketDataAgent
Fetches 2 years of daily OHLCV from Yahoo Finance and computes a full indicator suite. Produces a compact market summary that the next agent reads.

**Indicators computed (pure pandas, no C deps):**

| Indicator | Parameters |
|---|---|
| Simple Moving Average | 20-day, 50-day |
| Exponential Moving Average | 12-day, 26-day |
| RSI | 14-day |
| MACD | 12/26/9 |
| Bollinger Bands | 20-day, ±2σ |
| ATR | 14-day |

**Market summary output example:**
```
Close: 297.84 | SMA50: 266.78 | Trend: uptrend
ATR14: 6.67 (2.2% of price) | Volatility regime: moderate
RSI14: 82.6 (overbought)
Volume: 34,463,500 (below 20d avg)
Available indicators: SMA_20, SMA_50, EMA_12, EMA_26, RSI_14, MACD, BB_upper...
```

---

### 2 — StrategyAgent
Reads the market summary and asks GPT-4o to design a quantitative strategy suited to the current market conditions. Outputs a complete Python class plus a plain-English explanation.

**What GPT-4o must produce:**
- A class subclassing `backtesting.Strategy`
- All indicators wired through `self.I()` (required by `backtesting.py`)
- Entry/exit logic in `next()` using only past data (no look-ahead)
- Tunable class-level parameters (e.g. `n_fast = 20`)
- A stop-loss or position-sizing rule

Example output strategy skeleton:
```python
class RsiBollingerMean(Strategy):
    rsi_low = 35
    rsi_high = 65
    bb_period = 20

    def init(self):
        close = self.data.Close
        self.rsi = self.I(lambda x: ..., close)
        self.bb_upper = self.I(lambda x: ..., close)
        self.bb_lower = self.I(lambda x: ..., close)

    def next(self):
        if self.rsi[-1] < self.rsi_low and self.data.Close[-1] < self.bb_lower[-1]:
            self.buy(sl=self.data.Close[-1] * 0.95)
        elif self.rsi[-1] > self.rsi_high:
            self.sell()
```

---

### 3 — PythonMasterAgent
Runs deterministic static analysis on the generated code, then asks GPT-4o to repair any issues found. Repeats up to 3 times.

**Checks performed (AST-level, no code execution):**

| Check | What it catches |
|---|---|
| Syntax | `SyntaxError` — unparseable code |
| Strategy subclass | Class must extend `Strategy` |
| `init()` / `next()` presence | Both methods required |
| `self.I()` usage | Indicators not wrapped in `self.I()` cause runtime errors |
| Look-ahead bias | Positive index `self.data.Close[1]` peeks at future prices |
| Order calls | No `buy()` / `sell()` = strategy can never trade |
| Forbidden imports | `os`, `subprocess`, `sys`, `socket` blocked |
| Forbidden builtins | `open()`, `exec()`, `eval()` blocked |

**Repair loop:**
```
issues = check(code)
while issues and iteration < 3:
    code = gpt4o_repair(code, issues)
    issues = check(code)
    iteration++

→ approved (confidence score) or rejected (with root-cause)
```

The UI shows a **Code Review badge** with the score (0–100) and number of iterations used.

---

### 4 — BacktestAgent
Executes the approved strategy code in a sandboxed scope, runs `backtesting.py`'s simulation engine, and asks GPT-4o to write a narrative analysis.

**Execution sandbox:**
```python
scope = {
    "__builtins__": {"__build_class__": ..., "__name__": ...},
    "Strategy": Strategy,
    "crossover": crossover,   # backtesting.py helper
    "np": numpy,
    "pd": pandas,
}
exec(strategy_code, scope)
```
Only the above names are available inside the strategy. No filesystem, no network, no subprocess.

**Metrics computed:**

| Metric | Meaning |
|---|---|
| Total Return % | Raw gain/loss over the period |
| CAGR % | Annualised compound growth rate |
| Sharpe Ratio | Risk-adjusted return (higher = better) |
| Max Drawdown % | Worst peak-to-trough loss |
| Win Rate % | Fraction of trades that were profitable |
| Profit Factor | Gross profit / gross loss |
| Calmar Ratio | CAGR / abs(max drawdown) |
| # Trades | Total number of round-trip trades |
| Exposure % | Fraction of time the strategy held a position |

---

## Tools

| File | Functions | Used by |
|---|---|---|
| `src/tools/fetch_data.py` | `fetch_ohlcv(ticker, period)` | MarketDataAgent |
| `src/tools/indicators.py` | `compute_indicators(df)`, `market_summary(df)` | MarketDataAgent |
| `src/tools/code_validator.py` | `syntax_check`, `api_conformance_check`, `safety_check`, `run_all_checks` | PythonMasterAgent |
| `src/tools/backtest_runner.py` | `run_backtest(code, df, cash)` | BacktestAgent |
| `src/tools/db.py` | `save_strategy`, `save_code_review`, `save_backtest_run`, `get_*`, `list_*` | All agents via crew |

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/analyze?ticker=NVDA` | **SSE stream** — full pipeline |
| `POST` | `/api/run/{strategy_id}` | **SSE stream** — re-run saved strategy |
| `GET` | `/api/strategies` | List all saved strategies |
| `GET` | `/api/strategies/{id}` | Strategy detail + source code + review |
| `GET` | `/api/backtest/{id}` | Backtest result + equity curve + trade log |
| `GET` | `/api/history/{ticker}` | All backtest runs for a ticker |
| `GET` | `/health` | Health check |

---

## File Structure

```
agent_stock_system/
├── .env                          # OPENAI_API_KEY (not committed)
├── pyproject.toml                # uv project — Python 3.12, all deps
├── doc/
│   ├── design.md                 # system design decisions
│   └── implementation_plan.md   # phase-by-phase build plan
│
├── src/
│   ├── config.py                 # loads .env → typed constants
│   ├── main.py                   # FastAPI app, all routes, SSE endpoints
│   ├── crew.py                   # pipeline orchestrator (async SSE generators)
│   │
│   ├── agents/
│   │   ├── market_data.py        # MarketDataAgent + CrewAI task builder
│   │   ├── strategy.py           # StrategyAgent + response parser
│   │   ├── python_master.py      # PythonMasterAgent + repair loop
│   │   └── backtest.py           # BacktestAgent + narrative generator
│   │
│   ├── tools/
│   │   ├── fetch_data.py         # yfinance wrapper
│   │   ├── indicators.py         # pure-pandas SMA/EMA/RSI/MACD/BB/ATR
│   │   ├── code_validator.py     # AST-based static analysis
│   │   ├── backtest_runner.py    # sandboxed exec + metric extraction
│   │   └── db.py                 # SQLite: init, save, get, list
│   │
│   └── prompts/
│       ├── strategy_gen.txt      # system prompt: strategy generation rules
│       ├── code_review.txt       # system prompt: code repair rules
│       └── result_explain.txt    # system prompt: narrative format
│
├── frontend/
│   ├── index.html                # single-page app
│   ├── app.js                    # SSE handling, Chart.js charts, trade log
│   └── style.css                 # dark theme, responsive layout
│
└── data/
    └── stock.db                  # SQLite database (auto-created)
```

---

## How Quantitative Trading Works

Quantitative trading replaces human intuition with explicit, testable rules. A strategy is a set of mathematical conditions — derived from price, volume, and indicator data — that define exactly when to buy and sell. The goal is to find rules that produce consistent profit across many historical trades, not just one lucky guess.

### Indicators: reading the market's signal

Raw price data is noisy. Indicators smooth it or transform it to highlight structure:

**Trend indicators** — Is the market going up or down?
- `SMA(20)` = average closing price over the last 20 days. Price above SMA → uptrend.
- `EMA(12)` = same idea but recent prices weighted more heavily. Reacts faster.

**Momentum indicators** — Is the move speeding up or slowing down?
- `RSI(14)` — Relative Strength Index. Ranges 0–100.
  - Above 70 → overbought (momentum may exhaust)
  - Below 30 → oversold (potential reversal)
- `MACD` = EMA(12) − EMA(26). Positive = bullish momentum. The "signal line" (EMA of MACD) is used for crossovers.

**Volatility indicators** — How large are normal price swings?
- `Bollinger Bands` = SMA(20) ± 2 standard deviations. Price touching the lower band in an uptrend = potential entry. Wide bands = high volatility.
- `ATR(14)` = Average True Range. Measures daily price swing size. Used to set stop-losses proportional to current volatility (e.g. stop-loss = current price − 2× ATR).

### Strategy logic: entry and exit rules

A strategy answers two questions: **when to buy** and **when to sell**.

**Example — RSI + Bollinger Band mean-reversion:**
```
Entry:  RSI < 35  AND  price < BB_lower   → buy (price is cheap and oversold)
Exit:   RSI > 65  OR   price > BB_upper   → sell (price has recovered)
Stop:   entry price × 0.95               → forced exit if down 5%
```

This is a *mean-reversion* strategy: it bets that price will return toward its average after an extreme move. The opposite philosophy — *trend-following* — bets that a move will continue:

```
Entry:  SMA(20) crosses above SMA(50)   → buy (short-term trend now stronger)
Exit:   SMA(20) crosses below SMA(50)   → sell (trend reversed)
```

### Backtesting: does the strategy actually work?

Before risking real money, you test the strategy on historical data — this is backtesting. The simulator replays market history bar-by-bar, applying the exact entry/exit rules, and tracks what would have happened.

**What backtesting measures:**

| Metric | What it tells you |
|---|---|
| **Total Return %** | Did the strategy make money at all? |
| **CAGR %** | What annualised rate did it compound at? Compare to S&P 500 (~10% long-run). |
| **Sharpe Ratio** | Return per unit of risk. >1.0 is decent; >2.0 is excellent. Tells you if gains are consistent or just lucky volatility. |
| **Max Drawdown %** | The worst loss from a peak before recovery. −30% means you'd have had to watch your portfolio fall 30% at some point. Measures psychological and practical risk. |
| **Win Rate %** | Fraction of individual trades that made money. A 40% win rate can still be profitable if wins are large and losses are small (profit factor > 1). |
| **Profit Factor** | Gross profit ÷ gross loss. >1.0 means more money made than lost. |
| **# Trades** | More trades = more statistical confidence the result isn't luck. Fewer than 30 trades → treat results with skepticism. |

**The equity curve** is the single most important chart: it shows your portfolio value over time. A good strategy produces a smooth upward curve with shallow drawdowns. Jagged curves or long flat periods reveal hidden risks.

### Critical limitations to understand

**Overfitting (curve-fitting):** A strategy can be tuned to look perfect on past data but fail on future data because it memorised noise rather than learning genuine market structure. More parameters = higher overfitting risk. The system's PythonMasterAgent checks for one mechanical form of this (look-ahead bias), but economic overfitting is harder to detect.

**Look-ahead bias:** The most common bug in backtesting. If your strategy accidentally uses tomorrow's price to make today's decision (e.g. indexing `data.Close[1]` instead of `data.Close[-1]`), the backtest looks amazing but the strategy is impossible to trade in reality. The AST validator explicitly catches this.

**Transaction costs:** Every trade has a cost (spread, commission, slippage). This system models 0.2% round-trip commission. Real costs may be higher, especially for illiquid stocks or high-frequency strategies.

**Regime change:** A strategy that worked in a trending 2021 bull market may fail in a choppy 2022 bear market. A single 2-year backtest cannot guarantee robustness across all market conditions.

---

## Environment Variables

```bash
OPENAI_API_KEY=sk-...           # required
DB_PATH=./data/stock.db         # SQLite file location
DEFAULT_CAPITAL=10000           # starting portfolio value
DATA_PERIOD=2y                  # yfinance period (1y, 2y, 5y)
MAX_REVIEW_ITERATIONS=3         # PythonMasterAgent max repair loops
```
