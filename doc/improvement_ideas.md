# Improvement Ideas

Assessed against the current codebase (May 2026). Grouped by theme. Each item states what it is, why it matters, and roughly how hard it is.

---

## 1. Strategy Quality & Reliability

### 1.1 Walk-Forward Validation
**What:** After backtesting on the full 2-year window, automatically split the data into in-sample (first 70%) and out-of-sample (last 30%) and report both sets of metrics side by side.  
**Why:** A strategy that looks good on 2 years of data may be overfit. Walk-forward reveals whether the edge is real or just curve-fitting on the training window.  
**How:** In `backtest_runner.py`, run `Backtest` twice — once on `df[:split]`, once on `df[split:]`. Return both metric dicts. Show a "In-sample vs Out-of-sample" comparison table in the UI.  
**Effort:** Small (1–2 days).

### 1.2 Strategy Parameter Optimisation
**What:** Expose a "Optimize" button that uses `backtesting.py`'s built-in `bt.optimize()` to search the parameter grid defined in the strategy class.  
**Why:** The LLM picks default parameter values arbitrarily. A grid search over e.g. `fast ∈ [10,20,30]` and `slow ∈ [40,50,60]` can often double the Sharpe ratio.  
**How:** Call `bt.optimize(**param_ranges, maximize='Sharpe Ratio')` in a background task. Stream progress via SSE. Save the best params alongside the run.  
**Effort:** Medium (2–3 days). Watch for overfit — add a constraint that optimisation uses only in-sample data.

### 1.3 Monte Carlo Simulation
**What:** After a backtest, run 500+ random shuffles of the trade order and report the distribution of outcomes (5th/50th/95th percentile equity curves).  
**Why:** A strategy with only 30 trades has high variance. Monte Carlo shows whether the result is plausibly lucky or statistically robust.  
**How:** Shuffle `trade_log` rows repeatedly, recompute cumulative P&L, plot as a fan chart alongside the actual equity curve.  
**Effort:** Small (1 day, pure Python).

### 1.4 Multi-Ticker Comparison
**What:** Allow entering multiple tickers (e.g. `NVDA, AAPL, TSLA`) and run the same strategy type across all of them, returning a comparison table ranked by Sharpe.  
**Why:** Quickly surface which sectors or names the strategy works best on. Also useful for position sizing across a portfolio.  
**Effort:** Medium (parallel pipeline runs + merged UI table).

---

## 2. Data & Indicators

### 2.1 Longer History & Multiple Timeframes
**What:** Support `5y` and `10y` periods, and add an intraday option (`1h` bars via yfinance).  
**Why:** 2 years contains at most one full market cycle. A strategy that works across 5+ years and multiple regimes (bull/bear/choppy) is far more credible.  
**How:** Expose a period dropdown in the UI alongside the existing strategy dropdowns. Pass it through to `fetch_ohlcv`.  
**Effort:** Tiny (UI + one config change).

### 2.2 Fundamental Data Layer
**What:** Fetch key fundamentals (P/E, P/B, EPS growth, revenue growth) from yfinance's `Ticker.info` and include them in the market summary passed to the LLM.  
**Why:** The LLM currently only sees price/volume technicals. Adding "P/E = 35, sector median = 28" lets it generate fundamentally-informed strategies (e.g. value mean-reversion).  
**How:** Extend `market_data.py` with a `fundamental_summary(ticker)` function. Append to the market summary string.  
**Effort:** Small (1 day).

### 2.3 Sentiment / News Signal
**What:** Pull recent headlines via a free news API (e.g. Alpaca News, NewsAPI) and summarise sentiment with a quick LLM call before strategy generation.  
**Why:** Earnings surprises, product launches, and macro events are not visible in OHLCV data. A sentiment-aware strategy can avoid entering before bad news.  
**How:** Add a `SentimentAgent` step between `MarketDataAgent` and `StrategyAgent`. Classify headlines as positive/negative/neutral and append a short summary to the market context.  
**Effort:** Medium (2–3 days + API key).

### 2.4 Sector & Market Context
**What:** Include SPY/QQQ/sector ETF performance in the market summary (e.g. "SPY is up 12% YTD, XLK sector up 18%").  
**Why:** A stock trending up in a falling market is qualitatively different from one following the sector. This context helps the LLM pick regime-appropriate strategies.  
**Effort:** Small (fetch 2–3 extra yfinance tickers in `market_data.py`).

---

## 3. Code Generation & Validation

### 3.1 Execution-Based Validation (Dry Run)
**What:** Before the full backtest, try executing the strategy code on a tiny 10-row DataFrame. If it raises, feed the exact traceback into the repair loop.  
**Why:** Static AST checks catch structural issues but miss runtime errors like type mismatches, missing attributes, or division by zero in indicator logic.  
**How:** In `python_master.py`, add a `dry_run(source_code, mini_df)` step after AST checks. If it raises, prepend the traceback to the issues list.  
**Effort:** Small (1 day). Significantly reduces backtest failures.

### 3.2 Strategy Diversity — Prevent Duplicates
**What:** Before generating a new strategy, embed the last 5 strategies for the same ticker and instruct the LLM to generate something meaningfully different.  
**Why:** The LLM tends to converge on SMA-crossover + RSI for every ticker. The run history becomes repetitive and doesn't explore the strategy space.  
**How:** In `build_strategy_task`, fetch recent strategies from the DB and append "Avoid strategies similar to: [names + brief descriptions]" to the task.  
**Effort:** Small (1 day).

### 3.3 Strategy Library / Templates
**What:** Ship 10–15 hand-written, validated strategy templates (pairs trading, momentum, RSI mean-reversion, breakout, etc.) that the LLM can use as a starting point.  
**Why:** Starting from a known-good template reduces generation failures and produces better-structured code. The LLM's job becomes "adapt this template to the current market" rather than "write from scratch."  
**How:** Store templates in `src/prompts/templates/`. Show them as a "Starting point" dropdown in the UI.  
**Effort:** Medium (writing + validating templates is the work).

---

## 4. Backtesting Engine

### 4.1 Realistic Transaction Costs
**What:** Add a slippage model (e.g. 0.05% of price per trade, proportional to volume) on top of the fixed 0.2% commission.  
**Why:** Fixed commission underestimates real costs for illiquid stocks or large position sizes. Slippage is the bigger cost for active strategies.  
**How:** `backtesting.py` supports a custom `commission` callable. Pass a function that adds both spread and volume-impact components.  
**Effort:** Small (a few lines in `backtest_runner.py`).

### 4.2 Position Sizing Models
**What:** Allow the LLM (or user) to choose a position sizing rule: fixed fractional, Kelly criterion, volatility-targeting (size = `target_vol / ATR`).  
**Why:** Currently all strategies default to 100% of capital per trade. Proper sizing dramatically changes the risk/return profile.  
**How:** Add a `position_sizing` dropdown to the UI. Inject the chosen model into the strategy template.  
**Effort:** Medium (prompt engineering + UI).

### 4.3 Long/Short Strategies
**What:** Enable the LLM to generate strategies that can go short (currently `self.sell()` only closes longs, never opens shorts).  
**Why:** Bull-only strategies lose money in bear markets. A long/short strategy can profit in both directions.  
**How:** Explicitly allow `self.sell(size=...)` to open short positions in the prompt and sandbox. Add a "Allow short selling" toggle to the UI.  
**Effort:** Small prompt change, but requires careful validator update.

---

## 5. Infrastructure & Reliability

### 5.1 Background Job Queue (Celery / ARQ)
**What:** Move the CrewAI pipeline to a background worker (Celery + Redis, or ARQ + Redis) instead of running it in a FastAPI async thread.  
**Why:** Long-running LLM calls block the event loop, causing SSE timeouts for other users. A worker queue decouples request handling from computation.  
**How:** Replace `run_in_executor` with a task queue. The SSE endpoint polls job status from Redis/SQLite.  
**Effort:** Large (3–5 days). High priority if running with multiple concurrent users.

### 5.2 Rate Limiting & Cost Tracking
**What:** Track OpenAI token usage per run and expose a `/api/cost` endpoint. Optionally add per-IP rate limiting.  
**Why:** GPT-4o is expensive. Without tracking, a single heavy user can run up significant API costs unnoticed.  
**How:** Add `prompt_tokens` and `completion_tokens` columns to `backtest_runs`. Log from OpenAI response headers.  
**Effort:** Small (1 day).

### 5.3 Result Caching
**What:** Cache market data fetches by `(ticker, period, date)` for 24 hours in SQLite or a local file. Cache strategy generation by `(ticker, market_summary_hash, strategy_type, indicators)`.  
**Why:** Re-running the same ticker on the same day makes 4 identical LLM calls. Caching eliminates redundant cost and latency.  
**Effort:** Small–medium (1–2 days).

### 5.4 User Authentication & Multi-Tenancy
**What:** Add simple JWT-based auth so multiple users can have their own run history.  
**Why:** Without auth, all users share one history. Needed before any kind of public deployment.  
**How:** Add `user_id` columns to `strategies` and `backtest_runs`. Protect endpoints with a `Depends(get_current_user)` FastAPI dependency.  
**Effort:** Medium (2–3 days).

---

## 6. UI & UX

### 6.1 Strategy Comparison View
**What:** A dedicated page/panel showing all runs for a ticker as a sortable table — Sharpe, return, max DD, win rate — so the user can compare strategies at a glance.  
**Why:** Currently to compare two strategies you have to click each sidebar item individually. A table view is far more useful for evaluation.  
**Effort:** Small (1 day, frontend only).

### 6.2 Interactive Parameter Editing
**What:** Make the parameter table editable. When the user changes a value and clicks "Re-run", patch the saved strategy code with the new values and run the backtest without calling the LLM.  
**Why:** "What if `n_fast = 10` instead of `20`?" is a natural question after seeing a backtest. Currently requires regenerating the entire strategy.  
**How:** Edit parameter assignments in the source code with a regex replace, then call `run_backtest_pipeline` directly.  
**Effort:** Medium (1–2 days).

### 6.3 Candlestick Chart with Indicators
**What:** Replace the plain line "Price Action & Trade Signals" chart with a proper candlestick chart (OHLC bars) plus overlaid indicator lines (SMA, Bollinger Bands).  
**Why:** Quants think in candlestick charts. Seeing the strategy's signals in context with volume and candle patterns is much more informative than a close-price line.  
**How:** Use `lightweight-charts` (TradingView's open-source library) instead of Chart.js for this panel. Feed OHLCV from the existing `/api/backtest/{id}/rawdata` endpoint.  
**Effort:** Medium (2 days, frontend only).

### 6.4 Export to PDF Report
**What:** A "Download Report" button that generates a PDF containing the strategy explanation, metrics, charts, and trade log.  
**Why:** Users want to share results with colleagues or keep an offline record. A polished PDF report adds significant perceived value.  
**How:** Use `weasyprint` or `playwright` server-side to render the backtest panel to PDF.  
**Effort:** Medium (1–2 days).

---

## 7. Agent & LLM

### 7.1 Switch to Structured Output
**What:** Use OpenAI's `response_format={"type": "json_schema", ...}` (or `pydantic` via the Instructor library) to force the LLM to return a structured object `{code: str, explanation: str}` instead of free-form markdown.  
**Why:** Eliminates the fragile regex parsing in `parse_strategy_response`. The "No ```python``` block found" error would become impossible.  
**Effort:** Small (1 day). High value.

### 7.2 Strategy Self-Critique Agent
**What:** Add a fifth agent that reads the backtest results and critiques the strategy ("Win rate is 38% and max drawdown is 40% — the strategy is too aggressive. Suggested improvements: ..."), then proposes a refined version automatically.  
**Why:** The current `BacktestAgent` narrative describes what happened but doesn't propose fixes. A critique-and-refine loop could converge on better strategies.  
**Effort:** Medium (2–3 days).

### 7.3 Model Fallback Chain
**What:** If GPT-4o returns a bad response (fails parsing or validation after 3 retries), automatically fall back to `o1-mini` or `claude-3-5-sonnet` for that attempt.  
**Why:** GPT-4o is occasionally unavailable or rate-limited. A fallback chain keeps the system running.  
**Effort:** Small (1 day, wrap `_llm_repair` and `strategy_agent` calls).

---

## Priority Matrix

| Item | Impact | Effort | Recommended Order |
|---|---|---|---|
| 3.1 Execution dry-run | High | Small | **1** |
| 7.1 Structured output | High | Small | **2** |
| 1.1 Walk-forward validation | High | Small | **3** |
| 2.1 Longer history | Medium | Tiny | **4** |
| 6.2 Editable parameters | High | Medium | **5** |
| 1.2 Parameter optimisation | High | Medium | **6** |
| 6.3 Candlestick chart | Medium | Medium | **7** |
| 3.2 Strategy diversity | Medium | Small | **8** |
| 5.1 Background job queue | High | Large | **9 (when multi-user)** |
| 7.2 Self-critique agent | High | Medium | **10** |
