# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies (Python 3.12 required)
uv sync

# Run the server
uv run uvicorn src.main:app --reload --port 9000
# or via project script (port 8000):
uv run dev

# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/test_backtest_runner.py

# Run a single test
uv run pytest tests/test_db.py::test_name -v
```

## Environment

Requires `.env` with:
```
OPENAI_API_KEY=sk-...
```

Optional:
```
DB_PATH=./data/stock.db
DEFAULT_CAPITAL=10000
DATA_PERIOD=2y
MAX_REVIEW_ITERATIONS=3
```

## Architecture

**FastAPI + CrewAI + SQLite** pipeline triggered by a ticker symbol. All results stream to the browser via SSE.

**Request flow:**
1. `GET /api/analyze?ticker=NVDA` → `src/crew.py` orchestrates 4 sequential agents
2. Each agent emits SSE progress events; the browser renders them live
3. Final results (strategy code, backtest metrics, charts) are persisted to SQLite and returned

**Agent pipeline (strictly sequential):**

| Agent | File | What it does |
|---|---|---|
| MarketDataAgent | `src/agents/market_data.py` | Fetches 2yr OHLCV via yfinance, computes indicators, produces a market summary string |
| StrategyAgent | `src/agents/strategy.py` | Passes market summary to GPT-4o; receives a `backtesting.Strategy` subclass + explanation |
| PythonMasterAgent | `src/agents/python_master.py` | AST-level static analysis + GPT-4o repair loop (≤3 iterations) |
| BacktestAgent | `src/agents/backtest.py` | Sandboxed `exec()` of strategy, runs `backtesting.py`, generates narrative via GPT-4o |

**Key tool files:**
- `src/tools/code_validator.py` — AST checks: syntax, Strategy subclass, `self.I()` usage, look-ahead bias (`data.Close[1]`), forbidden imports/builtins
- `src/tools/backtest_runner.py` — sandboxed exec scope; only `Strategy`, `crossover`, `np`, `pd` available inside strategy code
- `src/tools/db.py` — SQLite schema: `strategies`, `code_reviews`, `backtest_runs` tables
- `src/tools/indicators.py` — pure-pandas indicators (SMA/EMA/RSI/MACD/BB/ATR); no C deps

**Frontend:** Single-page app in `frontend/` (vanilla JS + Chart.js). Consumes SSE stream from `/api/analyze` and REST endpoints for history.

**Saved strategies** in `strategies/` are generated Python files named `{TICKER}_{ClassName}_{id}.py` — used for re-running without an LLM call via `POST /api/run/{strategy_id}`.

## Important Constraints

- Strategy code runs in a restricted `exec()` sandbox — only `Strategy`, `crossover`, `np`, `pd` and minimal builtins are available. Never add network or filesystem access to the sandbox.
- The `backtesting.py` library requires all indicators to be wrapped in `self.I()` and all data access to use negative indices (`self.data.Close[-1]`). The validator enforces this.
- Python 3.12 exactly (pinned in `pyproject.toml`). The `uv.lock` must stay in sync.
