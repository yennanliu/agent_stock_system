# Stock Quantitative Trading System — Design Document

## Overview

An AI-powered quantitative trading system that generates, explains, and backtests trading strategies for any given stock ticker. Built on CrewAI agents orchestrating the full pipeline from data retrieval to visual reporting.

---

## Goals

- Generate executable quantitative trading strategies for any US stock
- Run backtests and present results with clear visualizations
- Keep the stack minimal, observable, and easy to extend
- Surface LLM reasoning as plain-English explanations alongside the numbers

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      Browser (HTML/JS)                  │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ Stock Input │  │ Strategy View│  │ Backtest View │  │
│  └──────┬──────┘  └──────┬───────┘  └───────┬───────┘  │
└─────────┼────────────────┼──────────────────┼──────────┘
          │                │  REST API         │
┌─────────▼────────────────▼──────────────────▼──────────┐
│                    FastAPI Server                        │
│  /api/strategy   /api/backtest   /api/history           │
└─────────────────────────┬───────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────┐
│                    CrewAI Crew                           │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ MarketData   │  │  Strategy    │  │  Backtest    │  │
│  │   Agent      │→ │   Agent      │→ │   Agent      │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
│         ↓                 ↓                  ↓          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ fetch OHLCV  │  │ gen strategy │  │ run backtest │  │
│  │ + indicators │  │ + src code   │  │ + explain    │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
└─────────────────────────┬───────────────────────────────┘
                          │
              ┌───────────▼───────────┐
              │       SQLite DB       │
              │  strategies · runs    │
              │  results · snapshots  │
              └───────────────────────┘
```

---

## Tech Stack

| Layer       | Choice          | Reason                                    |
|-------------|-----------------|-------------------------------------------|
| Agent framework | CrewAI      | Role-based agents, simple task chaining   |
| LLM         | OpenAI GPT-4o   | Code generation + explanation quality     |
| Data        | yfinance        | Free, no key required, reliable OHLCV     |
| Indicators  | pandas-ta       | Pure-pandas, no TA-Lib C dependency       |
| Backtest    | backtesting.py  | Lightweight, Pythonic, good defaults      |
| Server      | FastAPI         | Async, automatic OpenAPI docs             |
| DB          | SQLite          | Zero infrastructure, file-based           |
| Frontend    | HTML + JS       | No build step; Chart.js for charts        |
| Pkg manager | uv              | Fast, reproducible, PEP 723 compliant     |
| Config      | python-dotenv   | Loads `.env` at startup                   |

---

## Agents

### 1. MarketDataAgent
**Role:** Pull and enrich market data  
**Tools:** `fetch_ohlcv(ticker, period)`, `compute_indicators(df)`  
**Output:** enriched DataFrame with OHLCV + common indicators (SMA, EMA, RSI, MACD, Bollinger Bands, ATR, volume profile)

### 2. StrategyAgent
**Role:** Devise and code a quantitative strategy  
**Tools:** `generate_strategy(ticker, market_summary)`, `save_strategy(code, metadata)`  
**Output:**
- Python class subclassing `backtesting.Strategy`
- Plain-English explanation (entry/exit logic, risk rationale)
- Parameter table (lookback windows, thresholds, position sizing)

### 3. BacktestAgent
**Role:** Execute the strategy and interpret results  
**Tools:** `run_backtest(strategy_code, df)`, `compute_metrics(bt_result)`, `explain_results(metrics)`  
**Output:**
- Standard metrics (Sharpe, max drawdown, CAGR, win rate, profit factor)
- Equity curve data
- Trade log
- LLM-generated narrative: what worked, what didn't, suggested tuning

---

## Data Flow

```
User enters ticker (e.g. NVDA)
        │
        ▼
MarketDataAgent
  └─ yfinance pulls 2yr daily OHLCV
  └─ pandas-ta appends indicators
  └─ summary stats fed to next agent
        │
        ▼
StrategyAgent (OpenAI GPT-4o)
  └─ reads market summary + indicators available
  └─ generates Strategy class (Python src)
  └─ writes explanation in markdown
  └─ saved to SQLite: strategies table
        │
        ▼
BacktestAgent
  └─ exec() strategy class in sandboxed scope
  └─ backtesting.py runs simulation
  └─ metrics computed
  └─ LLM writes narrative explanation
  └─ saved to SQLite: backtest_runs table
        │
        ▼
API returns JSON → Browser renders charts + explanation
```

---

## Database Schema

```sql
CREATE TABLE strategies (
    id          INTEGER PRIMARY KEY,
    ticker      TEXT NOT NULL,
    name        TEXT NOT NULL,
    description TEXT,
    source_code TEXT NOT NULL,
    parameters  TEXT,           -- JSON
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE backtest_runs (
    id              INTEGER PRIMARY KEY,
    strategy_id     INTEGER REFERENCES strategies(id),
    ticker          TEXT NOT NULL,
    start_date      TEXT,
    end_date        TEXT,
    initial_capital REAL DEFAULT 10000,
    metrics         TEXT,       -- JSON: sharpe, cagr, max_dd, win_rate, ...
    equity_curve    TEXT,       -- JSON array [{date, equity}]
    trade_log       TEXT,       -- JSON array [{entry, exit, pnl, ...}]
    explanation     TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## API Endpoints

| Method | Path                         | Description                          |
|--------|------------------------------|--------------------------------------|
| POST   | `/api/analyze`               | Full pipeline: data → strategy → backtest |
| GET    | `/api/strategies`            | List all saved strategies            |
| GET    | `/api/strategies/{id}`       | Strategy detail + source code        |
| GET    | `/api/backtest/{id}`         | Backtest result + equity curve       |
| GET    | `/api/history/{ticker}`      | All runs for a ticker                |

Single `/api/analyze` call triggers the full CrewAI crew and streams progress via Server-Sent Events (SSE) so the UI shows live status.

---

## Frontend

Single-page app, no framework, no build step.

```
index.html
  ├── Search bar (ticker input)
  ├── Status log (SSE stream from /api/analyze)
  ├── Strategy Panel
  │     ├── Name + plain-English explanation
  │     ├── Parameter table
  │     └── Source code block (syntax highlighted via highlight.js)
  └── Backtest Panel
        ├── Metrics cards (Sharpe, CAGR, Max DD, Win Rate)
        ├── Equity Curve (Chart.js line)
        ├── Drawdown Chart (Chart.js area)
        ├── Trade Scatter (entry/exit on price chart)
        └── LLM Narrative (markdown rendered via marked.js)
```

**Libraries loaded from CDN (no npm):**
- `Chart.js` — equity curve, drawdown, trade overlay
- `highlight.js` — Python source code display
- `marked.js` — render LLM markdown explanation

---

## Visualization Details

### Equity Curve
- Line chart: strategy equity vs. buy-and-hold baseline
- X-axis: date, Y-axis: portfolio value
- Annotated with max drawdown period shading

### Drawdown Chart
- Area chart showing rolling drawdown %
- Color gradient: green → red as drawdown deepens

### Trade Chart
- Candlestick (OHLC) for the backtest period
- Green triangles: long entries; red triangles: exits
- Moving average overlays matching the strategy's logic

### Metrics Cards
```
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│  Sharpe  │ │   CAGR   │ │  Max DD  │ │ Win Rate │
│   1.84   │ │  23.4%   │ │  -12.1%  │ │  58.3%   │
└──────────┘ └──────────┘ └──────────┘ └──────────┘
```

---

## Project Structure

```
agent_stock_system/
├── .env                        # OPENAI_API_KEY, etc.
├── pyproject.toml              # uv project file
├── doc/
│   └── design.md               # this file
├── src/
│   ├── main.py                 # FastAPI app entry point
│   ├── crew.py                 # CrewAI crew definition
│   ├── agents/
│   │   ├── market_data.py      # MarketDataAgent
│   │   ├── strategy.py         # StrategyAgent
│   │   └── backtest.py         # BacktestAgent
│   ├── tools/
│   │   ├── fetch_data.py       # yfinance wrapper
│   │   ├── indicators.py       # pandas-ta helpers
│   │   ├── backtest_runner.py  # backtesting.py wrapper
│   │   └── db.py               # SQLite helpers (sqlite3 stdlib)
│   └── prompts/
│       ├── strategy_gen.txt    # system prompt for strategy generation
│       └── result_explain.txt  # system prompt for result narration
└── frontend/
    ├── index.html
    ├── app.js
    └── style.css
```

---

## Environment Setup

```
# .env
OPENAI_API_KEY=sk-...
DB_PATH=./data/stock.db
DEFAULT_CAPITAL=10000
DATA_PERIOD=2y
```

```bash
uv init agent_stock_system
uv add fastapi uvicorn crewai openai yfinance pandas-ta backtesting python-dotenv
uv run uvicorn src.main:app --reload
```

---

## Key Design Decisions

**Why `exec()` for strategy code?**  
The LLM generates a Python class. Running it with `exec()` in a controlled local scope is the simplest path. The scope is isolated (no builtins beyond what's needed) and all inputs are internal — not user-supplied strings — so the risk is acceptable.

**Why SSE instead of WebSockets?**  
CrewAI tasks are sequential. SSE is unidirectional and dead-simple: one `EventSourceResponse`, no upgrade handshake, works through proxies.

**Why backtesting.py over zipline/backtrader?**  
Zero C dependencies, vectorized by default, returns structured results as a dict. `backtesting.py` installs in seconds with uv.

**Why SQLite?**  
No server to run. Strategy source code and backtest results are text blobs — SQLite handles them perfectly. Concurrent writes are rare (one user, sequential agent pipeline).

---

## Milestones

| # | Milestone                                     | Deliverable                        |
|---|-----------------------------------------------|------------------------------------|
| 1 | Scaffold + data pipeline                      | `MarketDataAgent` returns enriched df |
| 2 | Strategy generation                           | GPT-4o generates valid Strategy class |
| 3 | Backtest runner + metrics                     | `BacktestAgent` returns metrics JSON |
| 4 | FastAPI + SQLite persistence                  | `/api/analyze` end-to-end works    |
| 5 | Frontend: metrics + equity curve              | Charts render from API data        |
| 6 | Frontend: source code view + LLM explanation  | Full UX complete                   |
| 7 | Polish: SSE progress, error states, history   | Production-ready MVP               |
