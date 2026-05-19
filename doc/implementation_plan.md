# Implementation Plan

## Prerequisites

```bash
uv init agent_stock_system
cd agent_stock_system
uv add fastapi uvicorn "crewai[tools]" openai yfinance pandas-ta backtesting python-dotenv
```

Create `.env`:
```
OPENAI_API_KEY=sk-...
DB_PATH=./data/stock.db
DEFAULT_CAPITAL=10000
DATA_PERIOD=2y
MAX_REVIEW_ITERATIONS=3
```

---

## Phase 1 — Project Scaffold

**Goal:** runnable skeleton with config, DB init, and a health-check endpoint.

### 1.1 Directory layout

```
mkdir -p src/agents src/tools src/prompts data frontend
touch src/__init__.py src/agents/__init__.py src/tools/__init__.py
```

### 1.2 `src/config.py`
- Load `.env` via `python-dotenv`
- Export typed constants: `OPENAI_API_KEY`, `DB_PATH`, `DEFAULT_CAPITAL`, `DATA_PERIOD`, `MAX_REVIEW_ITERATIONS`

### 1.3 `src/tools/db.py`
- `init_db()` — create tables on startup if not exist
- `save_strategy(ticker, name, description, source_code, parameters) → int`
- `save_code_review(strategy_id, confidence, issues, fixes, iterations, approved) → int`
- `save_backtest_run(strategy_id, ticker, start_date, end_date, metrics, equity_curve, trade_log, explanation) → int`
- `get_strategy(id) → dict`
- `get_backtest(id) → dict`
- `list_strategies() → list[dict]`
- `list_runs_for_ticker(ticker) → list[dict]`

Schema: exactly as in `design.md` — three tables: `strategies`, `code_reviews`, `backtest_runs`.

### 1.4 `src/main.py`
- FastAPI app
- `@app.on_event("startup")` calls `init_db()`
- `GET /health` returns `{"status": "ok"}`
- Placeholder routers for `/api/analyze`, `/api/run/{id}`, etc.

**Checkpoint:** `uv run uvicorn src.main:app --reload` starts without errors; `/health` returns 200.

---

## Phase 2 — Data Pipeline (MarketDataAgent)

**Goal:** given a ticker, return an enriched DataFrame and a compact market summary.

### 2.1 `src/tools/fetch_data.py`

```python
def fetch_ohlcv(ticker: str, period: str = "2y") -> pd.DataFrame:
    # yfinance download, return DataFrame with columns Open/High/Low/Close/Volume
    # raise ValueError if ticker unknown or data empty
```

### 2.2 `src/tools/indicators.py`

```python
def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    # pandas-ta: append SMA(20), SMA(50), EMA(12), EMA(26),
    # RSI(14), MACD, Bollinger Bands(20,2), ATR(14)
    # drop rows with NaN (warm-up period)
    # return enriched df

def market_summary(df: pd.DataFrame) -> str:
    # compact text block for the LLM:
    # trend (price vs SMA50), volatility regime (ATR/price %),
    # RSI level, recent volume vs avg, date range
```

### 2.3 `src/agents/market_data.py`

```python
from crewai import Agent, Task

market_data_agent = Agent(
    role="Market Data Analyst",
    goal="Fetch and enrich OHLCV data; produce a concise market summary.",
    backstory="...",
    tools=[fetch_ohlcv_tool, compute_indicators_tool],
    llm=...,
    verbose=True,
)

def build_market_data_task(ticker: str) -> Task:
    ...
```

Wrap `fetch_ohlcv` and `compute_indicators` as CrewAI `@tool` functions.

**Checkpoint:** call `fetch_ohlcv("NVDA")` and `compute_indicators(df)` in isolation; confirm shape and no NaNs.

---

## Phase 3 — Strategy Generation (StrategyAgent)

**Goal:** produce a valid `backtesting.Strategy` subclass and a plain-English explanation.

### 3.1 `src/prompts/strategy_gen.txt`

System prompt instructing GPT-4o to:
- Output exactly one Python code block containing the Strategy class
- Use only `self.I()` for indicator construction
- Include a `Parameters` dataclass for tunable values
- Follow the block with a `## Explanation` markdown section
- Never reference future prices in `next()`

### 3.2 `src/agents/strategy.py`

```python
strategy_agent = Agent(
    role="Quantitative Strategy Developer",
    goal="Design and implement a backtesting.py Strategy class.",
    backstory="...",
    llm=...,
    verbose=True,
)

def build_strategy_task(ticker: str, market_summary: str) -> Task:
    # context includes: ticker, market_summary, available indicators list
    # expected output: raw LLM response (code + explanation)
```

### 3.3 Response parser

```python
def parse_strategy_response(raw: str) -> tuple[str, str]:
    # extract ```python ... ``` block → source_code
    # extract ## Explanation section → explanation
    # raise ParseError if either missing
```

**Checkpoint:** given a market summary, StrategyAgent returns parseable output with a class that at least passes `ast.parse`.

---

## Phase 4 — Code Review & Repair (PythonMasterAgent)

**Goal:** guarantee the strategy code is correct before execution; self-heal up to 3 times.

### 4.1 `src/tools/code_validator.py`

```python
def syntax_check(src: str) -> list[str]:
    # ast.parse; return list of error strings (empty = pass)

def api_conformance_check(src: str) -> list[str]:
    # AST walk:
    # - class must subclass Strategy
    # - indicators must use self.I(), not direct pandas-ta calls
    # - next() must not index self.data with positive offsets (look-ahead)
    # - buy()/sell() calls present

def safety_check(src: str) -> list[str]:
    # - no bare division without NaN guard
    # - no import of os/subprocess/sys
    # - no open() or file I/O

def run_all_checks(src: str) -> list[str]:
    return syntax_check(src) + api_conformance_check(src) + safety_check(src)
```

### 4.2 `src/prompts/code_review.txt`

System prompt instructing GPT-4o to:
- Read the issue list
- Return only a corrected Python code block
- Explain each fix in a `## Fixes` section

### 4.3 `src/agents/python_master.py`

```python
python_master_agent = Agent(
    role="Python Master",
    goal="Review and repair strategy code until all checks pass.",
    backstory="...",
    tools=[run_all_checks_tool, fix_code_tool],
    llm=...,
    verbose=True,
)

def review_and_repair(source_code: str, max_iterations: int = 3) -> dict:
    # returns:
    # {
    #   "approved": bool,
    #   "source_code": str,       # final (possibly repaired) code
    #   "confidence": int,        # 0-100
    #   "issues_found": [...],
    #   "fixes_applied": [...],
    #   "iterations": int,
    # }
    for i in range(max_iterations):
        issues = run_all_checks(source_code)
        if not issues:
            return approved_result(source_code, i)
        source_code = llm_repair(source_code, issues)   # calls GPT-4o
    return rejected_result(source_code, issues)
```

**Checkpoint:** feed intentionally broken strategy code (e.g., look-ahead index, missing `self.I()`); confirm it repairs within 2 iterations and passes all checks.

---

## Phase 5 — Backtest Execution (BacktestAgent)

**Goal:** execute approved code, compute metrics, generate narrative.

### 5.1 `src/tools/backtest_runner.py`

```python
def run_backtest(source_code: str, df: pd.DataFrame, initial_cash: float = 10000) -> dict:
    # restricted exec scope: only backtesting + numpy + pandas visible
    scope = {"__builtins__": {}, "Strategy": Strategy, "np": np, "pd": pd}
    exec(compile(source_code, "<strategy>", "exec"), scope)
    StrategyClass = next(v for v in scope.values() if is_strategy_subclass(v))

    bt = Backtest(df, StrategyClass, cash=initial_cash, commission=0.002)
    stats = bt.run()

    return {
        "metrics": extract_metrics(stats),       # sharpe, cagr, max_dd, win_rate, ...
        "equity_curve": equity_series(stats),    # [{date, equity}]
        "trade_log": trade_log(stats),           # [{entry_date, exit_date, pnl, bars}]
    }

def extract_metrics(stats) -> dict:
    # pull named fields from backtesting.py stats Series
    # compute Calmar = CAGR / abs(max_dd)

def equity_series(stats) -> list[dict]:
    # stats._equity_curve → [{date: iso_str, equity: float}]

def trade_log(stats) -> list[dict]:
    # stats._trades → list of dicts
```

### 5.2 `src/prompts/result_explain.txt`

System prompt instructing GPT-4o to:
- Write a 3–5 paragraph markdown narrative
- Section 1: what drove returns (reference specific metrics)
- Section 2: what the drawdown profile reveals about risk
- Section 3: concrete, actionable tuning suggestions

### 5.3 `src/agents/backtest.py`

```python
backtest_agent = Agent(
    role="Backtest Analyst",
    goal="Run the strategy, compute metrics, and explain results.",
    backstory="...",
    tools=[run_backtest_tool, explain_results_tool],
    llm=...,
    verbose=True,
)
```

**Checkpoint:** run a known-good strategy (e.g., simple SMA crossover) on AAPL; verify metrics are non-zero and equity curve has the right shape.

---

## Phase 6 — CrewAI Crew + FastAPI Integration

**Goal:** wire agents into a crew; expose `/api/analyze` and `/api/run/{id}` with SSE.

### 6.1 `src/crew.py`

```python
from crewai import Crew, Process

def build_analyze_crew(ticker: str) -> Crew:
    # tasks: market_data → strategy → review → backtest (sequential)
    return Crew(
        agents=[market_data_agent, strategy_agent, python_master_agent, backtest_agent],
        tasks=[...],
        process=Process.sequential,
        verbose=True,
    )
```

### 6.2 SSE helper

```python
async def run_crew_with_sse(ticker: str):
    # generator that yields SSE events
    yield event("started", {"ticker": ticker})
    # ... kick off crew tasks one by one, yield after each
    yield event("complete", {"strategy_id": sid, "backtest_id": bid})
```

CrewAI task callbacks (`on_task_end`) emit the per-stage events.

### 6.3 `src/main.py` — full routes

```python
@app.post("/api/analyze")
async def analyze(ticker: str):
    return EventSourceResponse(run_crew_with_sse(ticker))

@app.post("/api/run/{strategy_id}")
async def rerun(strategy_id: int, period: str = "2y"):
    return EventSourceResponse(run_backtest_sse(strategy_id, period))

@app.get("/api/strategies")
async def strategies():
    return list_strategies()

@app.get("/api/strategies/{id}")
async def strategy_detail(id: int):
    return get_strategy(id)          # includes source_code + review report

@app.get("/api/backtest/{id}")
async def backtest_detail(id: int):
    return get_backtest(id)          # includes equity_curve + trade_log

@app.get("/api/history/{ticker}")
async def history(ticker: str):
    return list_runs_for_ticker(ticker)
```

**Checkpoint:** `curl -N http://localhost:8000/api/analyze?ticker=AAPL` streams SSE events through all four agent stages and writes rows to SQLite.

---

## Phase 7 — Frontend

**Goal:** single `index.html` that drives the full UX with no build step.

### 7.1 Layout skeleton (`frontend/index.html`)

```
<body>
  <header>  Stock Quant System  </header>
  <main>
    <section id="search">
      <input id="ticker" placeholder="e.g. NVDA" />
      <button id="analyzeBtn">Analyze</button>
    </section>

    <section id="status-log">  <!-- SSE events appear here -->  </section>

    <section id="strategy-panel" hidden>
      <h2 id="strategy-name"></h2>
      <p  id="strategy-explanation"></p>
      <table id="param-table"></table>
      <div id="review-badge"></div>
      <pre><code id="source-code" class="language-python"></code></pre>
      <button id="runBtn">▶ Run Again</button>
    </section>

    <section id="backtest-panel" hidden>
      <div id="metrics-row"></div>
      <canvas id="equity-chart"></canvas>
      <canvas id="drawdown-chart"></canvas>
      <canvas id="trade-chart"></canvas>
      <table id="trade-log"></table>
      <div id="narrative"></div>
    </section>
  </main>

  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <script src="app.js"></script>
</body>
```

### 7.2 `frontend/app.js` — key functions

```javascript
// SSE flow
function analyze(ticker) {
  const es = new EventSource(`/api/analyze?ticker=${ticker}`);
  es.onmessage = (e) => {
    const data = JSON.parse(e.data);
    appendStatusLog(data.stage, data.message);
    if (data.stage === "complete") {
      es.close();
      loadStrategy(data.strategy_id);
      loadBacktest(data.backtest_id);
    }
  };
}

// Render strategy panel
async function loadStrategy(id) { ... }   // fetch + populate DOM

// Charts
function renderEquityCurve(equityCurve, ticker) {
  // Chart.js line: strategy equity + buy-and-hold baseline
  // drawdown shading as a fill dataset
}

function renderDrawdownChart(equityCurve) {
  // compute rolling drawdown from equity series
  // Chart.js area with red fill
}

function renderTradeChart(ohlcv, trades) {
  // Chart.js bar (OHLC approximation) + scatter for entries/exits
}

// Re-run
document.getElementById("runBtn").onclick = () => {
  const es = new EventSource(`/api/run/${currentStrategyId}`);
  ...
};
```

### 7.3 `frontend/style.css`

- Clean sans-serif, dark sidebar, white content area
- Metrics row: 5 cards in a flex row, color-coded (green = good, red = bad thresholds)
- Code block: monospace, dark background, scrollable
- Review badge: green border if approved, red if rejected
- Responsive: stack panels vertically below 900px

**Checkpoint:** open `http://localhost:8000` (FastAPI also serves `frontend/` as static files), enter `AAPL`, watch SSE log fill in, see charts render.

---

## Phase 8 — Polish & Error Handling

### 8.1 Error states
- Invalid ticker → `fetch_ohlcv` raises `ValueError` → SSE emits `{"stage": "error", "message": "..."}` → red banner in UI
- Code rejected after 3 repair iterations → SSE emits error with root-cause text from PythonMasterAgent
- Backtest fails (e.g., no trades executed) → surface "no trades" message with explanation

### 8.2 History panel
- `GET /api/history/{ticker}` powers a collapsible run history list
- Each row shows: date, strategy name, Sharpe, CAGR, Max DD
- Click a row to load that backtest into the backtest panel without re-running

### 8.3 FastAPI static file serving

```python
from fastapi.staticfiles import StaticFiles
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
```

### 8.4 Logging
- Python `logging` to stdout; one log line per agent stage with ticker + elapsed ms
- SQLite writes logged at DEBUG level

---

## Milestone Summary

| # | Phase                        | Done when                                              |
|---|------------------------------|--------------------------------------------------------|
| 1 | Scaffold                     | `/health` returns 200; DB tables created on startup    |
| 2 | Data pipeline                | `fetch_ohlcv` + `compute_indicators` return clean df   |
| 3 | Strategy generation          | StrategyAgent output parses to valid class + explanation |
| 4 | Code review + repair         | Broken code self-heals; clean code approved in 0 iterations |
| 5 | Backtest execution           | Known strategy on AAPL returns correct metrics         |
| 6 | Crew + FastAPI + SSE         | `/api/analyze` streams all 4 stages end-to-end         |
| 7 | Frontend                     | Charts render; [▶ Run Again] works                     |
| 8 | Polish                       | Error states, history panel, static serving            |

---

## Development Order Notes

- Build and test each `src/tools/` function in isolation before wiring into an agent.
- Add agents one at a time: get MarketData working, then Strategy, then PythonMaster, then Backtest — confirm each agent's output before chaining to the next.
- Use a fixed ticker (`AAPL`) for all early testing so you're not burning API tokens on data variance.
- The PythonMasterAgent's `review_and_repair` loop can be tested entirely without CrewAI — call it as a plain function with hand-crafted broken strategy strings.
- Frontend can be developed against mock JSON responses (`/api/analyze` stub) before the backend is complete.
