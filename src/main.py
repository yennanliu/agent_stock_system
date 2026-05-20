import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from src.config import DEFAULT_CAPITAL, DATA_PERIOD
from src.tools.db import (
    init_db,
    get_strategy,
    get_backtest,
    get_strategy_filepath,
    get_run_source_path,
    get_run_raw_data_path,
    list_strategies,
    list_runs_for_ticker,
    STRATEGIES_DIR,
)
from src.tools.job_queue import create_job, job_status, stream_job, start_pipeline_job

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    log.info("Database initialised")
    yield


app = FastAPI(title="Stock Quant System", lifespan=lifespan)


# ── SSE pipeline endpoints ────────────────────────────────────────────────────

@app.get("/api/analyze")
async def analyze(
    ticker: str = Query(..., description="Stock ticker, e.g. NVDA"),
    strategy_type: str = Query("auto", description="Strategy style: trend_following, mean_reversion, momentum, breakout, auto"),
    indicators: str = Query("auto", description="Indicators to use: sma, ema, rsi, macd, bollinger, atr, combined, auto"),
    period: str = Query(DATA_PERIOD, description="Data period: 1y, 2y, 5y, 10y"),
):
    """Full pipeline streamed via SSE, backed by the background job queue."""
    from src.crew import run_analyze_pipeline

    job_id = create_job(ticker.upper())

    def _factory():
        return run_analyze_pipeline(
            ticker.upper(),
            strategy_type=strategy_type,
            indicators=indicators,
            period=period,
        )

    start_pipeline_job(job_id, _factory)
    return EventSourceResponse(stream_job(job_id))


@app.get("/api/jobs/{job_id}/status")
async def get_job_status(job_id: str):
    status = job_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return status


@app.get("/api/jobs/{job_id}/stream")
async def reconnect_job_stream(job_id: str):
    """Reconnect to a running or completed job's SSE stream."""
    if job_status(job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return EventSourceResponse(stream_job(job_id))


@app.get("/api/run/{strategy_id}")
async def rerun(strategy_id: int, period: str = Query(DATA_PERIOD)):
    """Re-run a saved strategy with fresh market data (skips generation)."""
    from src.crew import run_backtest_pipeline

    strategy = get_strategy(strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found")

    job_id = create_job(strategy["ticker"])
    start_pipeline_job(job_id, lambda: run_backtest_pipeline(strategy, period))
    return EventSourceResponse(stream_job(job_id))


# ── REST read endpoints ───────────────────────────────────────────────────────

@app.get("/api/strategies")
async def strategies_list():
    return list_strategies()


@app.get("/api/strategies/{strategy_id}")
async def strategy_detail(strategy_id: int):
    row = get_strategy(strategy_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return row


@app.get("/api/backtest/{run_id}")
async def backtest_detail(run_id: int):
    row = get_backtest(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    return row


@app.get("/api/backtest/{run_id}/source")
async def run_source(run_id: int):
    """Return the strategy code snapshot saved at the time of this run."""
    row = get_backtest(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    # Prefer file on disk; fall back to DB column
    path = get_run_source_path(run_id)
    if path:
        code = path.read_text(encoding="utf-8")
    elif row.get("source_code"):
        code = row["source_code"]
    else:
        raise HTTPException(status_code=404, detail="Source code not available for this run")
    ticker = row.get("ticker", "strategy")
    return PlainTextResponse(
        code,
        media_type="text/x-python",
        headers={"Content-Disposition": f'attachment; filename="run_{run_id}_{ticker}.py"'},
    )


@app.get("/api/backtest/{run_id}/ohlcv")
async def run_ohlcv(run_id: int):
    """Return OHLCV data for this run as JSON (for candlestick chart)."""
    path = get_run_raw_data_path(run_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Raw data not available for this run")
    try:
        import pandas as pd
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        out = []
        for idx, row in df.iterrows():
            out.append({
                "time":   str(idx.date()),
                "open":   round(float(row["Open"]),  4),
                "high":   round(float(row["High"]),  4),
                "low":    round(float(row["Low"]),   4),
                "close":  round(float(row["Close"]), 4),
                "volume": int(row["Volume"]) if "Volume" in row else 0,
            })
        return out
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/backtest/{run_id}/rawdata")
async def run_raw_data(run_id: int):
    """Download the raw OHLCV + indicator CSV saved for this run."""
    path = get_run_raw_data_path(run_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Raw data not available for this run")
    row = get_backtest(run_id)
    ticker = row.get("ticker", "data") if row else "data"
    return FileResponse(
        str(path),
        media_type="text/csv",
        filename=f"run_{run_id}_{ticker}_raw.csv",
    )


@app.get("/api/history/{ticker}")
async def history(ticker: str):
    return list_runs_for_ticker(ticker.upper())


@app.get("/api/strategies/{strategy_id}/source")
async def strategy_source(strategy_id: int):
    """Return the saved .py file as plain text for download."""
    path = get_strategy_filepath(strategy_id)
    if path is None:
        # Fall back to DB source_code if file was deleted
        row = get_strategy(strategy_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Strategy not found")
        return PlainTextResponse(row["source_code"], media_type="text/x-python")
    return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="text/x-python")


@app.get("/api/strategies/{strategy_id}/runner")
async def strategy_runner(strategy_id: int):
    """Download the standalone runner script for this strategy."""
    import re as _re
    row = get_strategy(strategy_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    safe_name = _re.sub(r"[^\w]", "_", row["name"])
    runner_path = STRATEGIES_DIR / f"{row['ticker']}_{safe_name}_{strategy_id}_run.py"
    if not runner_path.exists():
        # Regenerate on demand
        from src.tools.db import _write_runner, _strategy_filename
        strat_path = _strategy_filename(strategy_id, row["ticker"], row["name"])
        _write_runner(runner_path, strat_path.name, row["ticker"], row["name"], strategy_id)
    filename = runner_path.name
    return FileResponse(str(runner_path), media_type="text/x-python", filename=filename)


@app.get("/api/strategies/{strategy_id}/download")
async def strategy_download(strategy_id: int):
    """Download the saved .py file."""
    path = get_strategy_filepath(strategy_id)
    row = get_strategy(strategy_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    filename = f"{row['ticker']}_{row['name']}_{strategy_id}.py"
    if path and path.exists():
        return FileResponse(str(path), media_type="text/x-python", filename=filename)
    # Fallback: serve from DB
    return PlainTextResponse(row["source_code"], media_type="text/x-python",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/api/runs")
async def all_runs():
    """All backtest runs across all tickers, newest first (for history browser)."""
    from src.tools.db import _conn
    import json
    with _conn() as con:
        rows = con.execute(
            """SELECT br.id, br.strategy_id, br.ticker, br.start_date, br.end_date,
                      br.metrics, br.created_at, s.name as strategy_name
               FROM backtest_runs br
               JOIN strategies s ON s.id = br.strategy_id
               ORDER BY br.created_at DESC, br.id DESC
               LIMIT 100"""
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        if d.get("metrics"):
            d["metrics"] = json.loads(d["metrics"])
        result.append(d)
    return result


@app.get("/api/strategies/{strategy_id}/optimize")
async def optimize_strategy(
    strategy_id: int,
    period: str = Query(DATA_PERIOD),
    maximize: str = Query("Sharpe Ratio", description="Metric to maximize"),
):
    """Grid-search strategy parameters via SSE. Streams progress then returns best params."""
    from src.tools.fetch_data import fetch_ohlcv
    from src.tools.indicators import compute_indicators
    from src.tools.backtest_runner import optimize_backtest

    strategy = get_strategy(strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found")

    async def stream():
        def _sse(stage, msg, **kw):
            return {"data": json.dumps({"stage": stage, "message": msg, **kw})}

        yield _sse("optimize", f"Fetching data for {strategy['ticker']} ({period})…")
        await asyncio.sleep(0)
        try:
            df = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: compute_indicators(fetch_ohlcv(strategy["ticker"], period)),
            )
        except Exception as e:
            yield _sse("error", f"Data fetch failed: {e}")
            return

        yield _sse("optimize", f"Running parameter grid search (maximize: {maximize})…")
        await asyncio.sleep(0)
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: optimize_backtest(strategy["source_code"], df, maximize=maximize),
            )
        except RuntimeError as e:
            yield _sse("error", str(e))
            return

        if not result:
            yield _sse("optimize_done", "No tunable parameters found in this strategy.", best_params={}, metrics={})
            return

        bp = result["best_params"]
        m  = result["metrics"]
        yield _sse(
            "optimize_done",
            f"Best params found. Sharpe: {m.get('sharpe', '—')} | Return: {m.get('total_return_pct', '—')}%",
            best_params=bp,
            metrics=m,
            strategy_id=strategy_id,
        )

    return EventSourceResponse(stream())


@app.get("/api/strategies/{strategy_id}/run-with-params")
async def run_with_params(
    strategy_id: int,
    params: str = Query("{}", description="JSON object of param overrides, e.g. {\"n_fast\":10}"),
    period: str = Query(DATA_PERIOD),
):
    """Re-run a strategy with patched parameter values (no LLM call)."""
    from src.crew import run_backtest_pipeline

    strategy = get_strategy(strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found")

    try:
        param_overrides = json.loads(params)
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="'params' must be a valid JSON object")

    # Patch numeric parameter assignments in the source code
    patched_code = strategy["source_code"]
    for name, value in param_overrides.items():
        if isinstance(value, (int, float)):
            patched_code = re.sub(
                rf"^(\s*{re.escape(name)}\s*=\s*)[\d.]+",
                lambda m, v=value: f"{m.group(1)}{v}",
                patched_code,
                flags=re.MULTILINE,
            )

    patched_strategy = dict(strategy)
    patched_strategy["source_code"] = patched_code
    # Update parameters dict for display
    patched_strategy["parameters"] = {**strategy.get("parameters", {}), **param_overrides}

    async def stream():
        async for event in run_backtest_pipeline(patched_strategy, period):
            yield event

    return EventSourceResponse(stream())


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def root():
    return FileResponse("frontend/index.html")


# ── Static assets ─────────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="frontend"), name="static")
