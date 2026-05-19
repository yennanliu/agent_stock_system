# Stock Quantitative Trading System — Design Document

## Overview

An AI-powered quantitative trading system that generates, reviews, and backtests trading strategies for any given stock ticker. A dedicated Python Master Agent ensures generated code is production-quality before it ever runs. Results — metrics, charts, and LLM narratives — are shown live in the browser.

---

## Goals

- Generate executable quantitative trading strategies for any US stock
- Guarantee code quality via a dedicated review-and-repair agent before execution
- Run backtests and present results with clear visualizations
- Keep the stack minimal, observable, and easy to extend
- Surface LLM reasoning as plain-English explanations alongside the numbers

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        Browser (HTML/JS)                     │
│  ┌─────────────┐  ┌───────────────┐  ┌────────────────────┐ │
│  │ Stock Input │  │ Strategy View │  │   Backtest View    │ │
│  │             │  │ • explanation │  │ • metrics cards    │ │
│  │  [NVDA] ▶  │  │ • source code │  │ • equity curve     │ │
│  │             │  │ • [▶ Run]     │  │ • trade chart      │ │
│  └──────┬──────┘  └──────┬────────┘  └────────────────────┘ │
└─────────┼────────────────┼────────────────────────────────────┘
          │                │  REST + SSE
┌─────────▼────────────────▼────────────────────────────────────┐
│                       FastAPI Server                          │
│  POST /api/analyze      GET /api/strategies                   │
│  POST /api/run/{id}     GET /api/backtest/{id}                │
│  GET  /api/history/{ticker}                                   │
└─────────────────────────┬──────────────────────────────────────┘
                          │
┌─────────────────────────▼──────────────────────────────────────┐
│                       CrewAI Crew                              │
│                                                                │
│  ┌────────────┐   ┌────────────┐   ┌────────────┐             │
│  │ MarketData │→  │  Strategy  │→  │  Python    │             │
│  │   Agent    │   │   Agent    │   │   Master   │             │
│  └────────────┘   └────────────┘   │   Agent    │             │
│                                    └─────┬──────┘             │
│                                    retry loop (max 3)          │
│                                    until code passes          │
│                                          │                     │
│                                    ┌─────▼──────┐             │
│                                    │  Backtest  │             │
│                                    │   Agent    │             │
│                                    └────────────┘             │
└─────────────────────────┬──────────────────────────────────────┘
                          │
              ┌───────────▼───────────┐
              │       SQLite DB       │
              │  strategies · runs    │
              │  code_reviews         │
              └───────────────────────┘
```

---

## Tech Stack

| Layer           | Choice         | Reason                                    |
|-----------------|----------------|-------------------------------------------|
| Agent framework | CrewAI         | Role-based agents, simple task chaining   |
| LLM             | OpenAI GPT-4o  | Code generation + explanation quality     |
| Data            | yfinance       | Free, no key required, reliable OHLCV     |
| Indicators      | pandas-ta      | Pure-pandas, no TA-Lib C dependency       |
| Backtest        | backtesting.py | Lightweight, Pythonic, structured output  |
| Server          | FastAPI        | Async, SSE support, automatic docs        |
| DB              | SQLite         | Zero infrastructure, file-based           |
| Frontend        | HTML + JS      | No build step; Chart.js for charts        |
| Pkg manager     | uv             | Fast, reproducible, PEP 723 compliant     |
| Config          | python-dotenv  | Loads `.env` at startup                   |

---

## Agents

### 1. MarketDataAgent
**Role:** Pull and enrich market data  
**Tools:** `fetch_ohlcv(ticker, period)`, `compute_indicators(df)`  
**Output:** enriched DataFrame with OHLCV + indicators (SMA, EMA, RSI, MACD, Bollinger Bands, ATR, volume profile) plus a compact market summary (trend, volatility regime, notable patterns)

### 2. StrategyAgent
**Role:** Devise a quantitative strategy and write the initial Python implementation  
**Tools:** `generate_strategy(ticker, market_summary)`, `save_draft(code, metadata)`  
**Output:**
- Python class subclassing `backtesting.Strategy`
- Plain-English explanation (entry/exit logic, risk rationale)
- Parameter table (lookback windows, thresholds, position sizing)

### 3. PythonMasterAgent  ← new
**Role:** Senior code reviewer and repair agent. Guarantees the strategy code is correct, clean, and safe before execution.  
**Tools:** `lint_code(src)`, `validate_api_usage(src)`, `fix_code(src, issues)`, `approve_code(src)`  
**Checks performed:**
- Syntax validity (`ast.parse`)
- `backtesting.py` API conformance (correct `self.I()` calls, `next()` signature, no forbidden globals)
- Logical soundness (no look-ahead bias, no division-by-zero hotspots, NaN guard)
- Code quality (naming, no dead code, PEP 8)
- Risk management present (stop-loss or position sizing logic)

**Repair loop:** if any check fails, the agent rewrites the offending section and re-validates — up to 3 iterations. If still failing after 3 attempts, it returns a structured error with a root-cause explanation so the UI can surface it clearly.

**Output:** approved source code + a review report (issues found, fixes applied, confidence score 0–100)

### 4. BacktestAgent
**Role:** Execute the approved strategy and interpret results  
**Tools:** `run_backtest(strategy_code, df)`, `compute_metrics(bt_result)`, `explain_results(metrics, strategy_explanation)`  
**Output:**
- Standard metrics (Sharpe, max drawdown, CAGR, win rate, profit factor, Calmar ratio)
- Equity curve time series
- Trade log (entry date, exit date, size, P&L, holding period)
- LLM narrative: what drove returns, what the drawdown reveals, concrete tuning suggestions

---

## Data Flow

```
User enters ticker (e.g. NVDA)
        │
        ▼
MarketDataAgent
  └─ yfinance: 2yr daily OHLCV
  └─ pandas-ta: indicators
  └─ emit SSE: "Market data ready"
        │
        ▼
StrategyAgent (GPT-4o)
  └─ reads market summary + available indicators
  └─ generates Strategy class draft + explanation
  └─ emit SSE: "Strategy draft generated"
        │
        ▼
PythonMasterAgent (GPT-4o)
  └─ ast.parse → syntax check
  └─ static analysis: API conformance, look-ahead, NaN
  └─ [fail] → rewrite + re-check (up to 3×)
  └─ [pass] → approve + write review report
  └─ save to SQLite: code_reviews table
  └─ emit SSE: "Code approved (score: 94/100)" or "Code error: <reason>"
        │
        ▼
BacktestAgent
  └─ exec() approved code in isolated scope
  └─ backtesting.py simulation
  └─ metrics computed
  └─ GPT-4o writes narrative
  └─ save to SQLite: backtest_runs table
  └─ emit SSE: "Backtest complete"
        │
        ▼
API returns full result JSON
Browser renders charts + source + explanation
```

### Re-run an existing strategy

The user can hit **[▶ Run]** on any saved strategy without re-generating it. This calls `POST /api/run/{strategy_id}`, which skips MarketDataAgent + StrategyAgent + PythonMasterAgent and goes straight to BacktestAgent with fresh market data.

```
[▶ Run] click
        │
        ▼
POST /api/run/{id}
  └─ load approved code from SQLite
  └─ fetch fresh OHLCV (same ticker, configurable period)
  └─ BacktestAgent → new backtest_run row
  └─ SSE stream → browser updates charts
```

---

## Database Schema

```sql
CREATE TABLE strategies (
    id          INTEGER PRIMARY KEY,
    ticker      TEXT NOT NULL,
    name        TEXT NOT NULL,
    description TEXT,
    source_code TEXT NOT NULL,       -- approved code from PythonMasterAgent
    parameters  TEXT,                -- JSON: param names + default values
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE code_reviews (
    id            INTEGER PRIMARY KEY,
    strategy_id   INTEGER REFERENCES strategies(id),
    confidence    INTEGER,           -- 0–100 score from PythonMasterAgent
    issues_found  TEXT,              -- JSON array of issue descriptions
    fixes_applied TEXT,              -- JSON array of fix descriptions
    iterations    INTEGER,           -- how many repair loops were needed
    approved      INTEGER,           -- 1 = passed, 0 = rejected
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE backtest_runs (
    id              INTEGER PRIMARY KEY,
    strategy_id     INTEGER REFERENCES strategies(id),
    ticker          TEXT NOT NULL,
    start_date      TEXT,
    end_date        TEXT,
    initial_capital REAL DEFAULT 10000,
    metrics         TEXT,            -- JSON: sharpe, cagr, max_dd, win_rate, ...
    equity_curve    TEXT,            -- JSON array [{date, equity}]
    trade_log       TEXT,            -- JSON array [{entry, exit, pnl, bars}]
    explanation     TEXT,            -- LLM narrative markdown
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## API Endpoints

| Method | Path                      | Description                                          |
|--------|---------------------------|------------------------------------------------------|
| POST   | `/api/analyze`            | Full pipeline: data → strategy → review → backtest   |
| POST   | `/api/run/{strategy_id}`  | Re-run saved strategy with fresh data (skip gen)     |
| GET    | `/api/strategies`         | List all saved strategies                            |
| GET    | `/api/strategies/{id}`    | Strategy detail: source code + review report         |
| GET    | `/api/backtest/{id}`      | Backtest result + equity curve + trade log           |
| GET    | `/api/history/{ticker}`   | All runs for a ticker, newest first                  |

Both `POST /api/analyze` and `POST /api/run/{id}` stream progress via **Server-Sent Events**. The browser `EventSource` receives one event per agent stage, driving the live status log.

---

## Frontend

Single-page app, no framework, no build step.

```
index.html
  ├── Search bar (ticker input + Analyze button)
  ├── Live status log (SSE: agent stage updates)
  │
  ├── Strategy Panel
  │     ├── Strategy name + plain-English explanation
  │     ├── Parameter table
  │     ├── Code Review badge (score + issues summary)
  │     ├── Source code block (highlight.js, Python)
  │     └── [▶ Run Again] button → POST /api/run/{id}
  │
  └── Backtest Panel
        ├── Metrics row: Sharpe · CAGR · Max DD · Win Rate · Profit Factor
        ├── Equity Curve chart (strategy vs. buy-and-hold)
        ├── Drawdown chart
        ├── Trade chart (price + entry/exit markers + MA overlays)
        ├── Trade log table (sortable)
        └── LLM Narrative (marked.js markdown)
```

**CDN libraries (no npm, no build):**
- `Chart.js` — equity curve, drawdown, trade overlay
- `highlight.js` — Python source code display
- `marked.js` — render LLM markdown explanation

---

## Visualization Details

### Equity Curve
- Line chart: strategy equity vs. buy-and-hold baseline
- X-axis: date · Y-axis: portfolio value normalised to 100
- Max drawdown period shaded in translucent red

### Drawdown Chart
- Area chart: rolling drawdown % from peak
- Color gradient: 0% → green, deepest → red

### Trade Chart
- OHLC bars for the full backtest period
- ▲ green triangles: entries · ▼ red triangles: exits
- Moving average lines matching the strategy's own indicators

### Metrics Row
```
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│  Sharpe  │ │   CAGR   │ │  Max DD  │ │ Win Rate │ │  Profit  │
│   1.84   │ │  23.4%   │ │  -12.1%  │ │  58.3%   │ │  Factor  │
│          │ │          │ │          │ │          │ │   1.72   │
└──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘
```

### Code Review Badge
```
┌──────────────────────────────────────┐
│ ✓ Code Review  Score: 94/100         │
│   2 issues found · 2 fixes applied   │
│   Iterations: 1                      │
└──────────────────────────────────────┘
```

---

## Project Structure

```
agent_stock_system/
├── .env                          # OPENAI_API_KEY, DB_PATH, etc.
├── pyproject.toml                # uv project file
├── doc/
│   └── design.md                 # this file
├── src/
│   ├── main.py                   # FastAPI app + SSE endpoints
│   ├── crew.py                   # CrewAI crew definition
│   ├── agents/
│   │   ├── market_data.py        # MarketDataAgent
│   │   ├── strategy.py           # StrategyAgent
│   │   ├── python_master.py      # PythonMasterAgent (review + repair)
│   │   └── backtest.py           # BacktestAgent
│   ├── tools/
│   │   ├── fetch_data.py         # yfinance wrapper
│   │   ├── indicators.py         # pandas-ta helpers
│   │   ├── code_validator.py     # ast.parse + API conformance checks
│   │   ├── backtest_runner.py    # backtesting.py wrapper + exec()
│   │   └── db.py                 # SQLite helpers (stdlib sqlite3)
│   └── prompts/
│       ├── strategy_gen.txt      # system prompt: strategy generation
│       ├── code_review.txt       # system prompt: code review + repair
│       └── result_explain.txt    # system prompt: backtest narration
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
MAX_REVIEW_ITERATIONS=3
```

```bash
uv init agent_stock_system
uv add fastapi uvicorn crewai openai yfinance pandas-ta backtesting python-dotenv
uv run uvicorn src.main:app --reload
```

---

## Key Design Decisions

**Why a dedicated PythonMasterAgent?**  
LLM-generated code has predictable failure modes: off-by-one indicator indices, look-ahead bias from using future closes in signals, missing `self.I()` wrapping. A specialist agent with deterministic static checks (`ast.parse`, regex for banned patterns) catches these before they corrupt backtest results. The repair loop keeps the pipeline self-healing without human intervention.

**Why `exec()` for strategy code?**  
The LLM generates a Python class; `exec()` in a controlled local scope with a restricted `__builtins__` is the simplest path to running it. Inputs are always internal (approved code from PythonMasterAgent, not raw user strings), so the risk is contained.

**Why a separate `/api/run/{id}` endpoint?**  
Re-running a saved strategy is a common action (different time period, different capital). Skipping the generation + review stages makes it fast and cheap — no LLM calls needed, just fresh data + backtesting.py.

**Why SSE instead of WebSockets?**  
CrewAI tasks are sequential. SSE is unidirectional and dead-simple: one `EventSourceResponse`, no upgrade handshake, works through proxies. Each agent stage emits one event.

**Why backtesting.py over zipline/backtrader?**  
Zero C dependencies, vectorized by default, returns structured results as a dict. Installs in seconds with uv.

**Why SQLite?**  
No server to run. Strategy source code and backtest results are text blobs — SQLite handles them perfectly. Sequential writes from one user; no concurrency concerns.

---

## Milestones

| # | Milestone                                       | Deliverable                              |
|---|-------------------------------------------------|------------------------------------------|
| 1 | Scaffold + data pipeline                        | MarketDataAgent returns enriched df      |
| 2 | Strategy generation                             | GPT-4o generates Strategy class draft    |
| 3 | PythonMasterAgent: static checks + repair loop  | Code passes validation before execution  |
| 4 | Backtest runner + metrics                       | BacktestAgent returns metrics JSON       |
| 5 | FastAPI + SQLite + SSE                          | `/api/analyze` streams end-to-end        |
| 6 | `/api/run/{id}` re-run flow                     | [▶ Run] button works in UI               |
| 7 | Frontend: charts + code view + narrative        | Full UX complete                         |
| 8 | Polish: error states, history panel, review badge | Production-ready MVP                   |
