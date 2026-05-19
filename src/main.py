import asyncio
import json
import logging
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
    list_strategies,
    list_runs_for_ticker,
)

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
async def analyze(ticker: str = Query(..., description="Stock ticker, e.g. NVDA")):
    """Full pipeline: data → strategy → review → backtest, streamed via SSE."""
    from src.crew import run_analyze_pipeline

    async def stream():
        async for event in run_analyze_pipeline(ticker.upper()):
            yield event

    return EventSourceResponse(stream())


@app.post("/api/run/{strategy_id}")
async def rerun(strategy_id: int, period: str = Query(DATA_PERIOD)):
    """Re-run a saved strategy with fresh market data (skips generation)."""
    from src.crew import run_backtest_pipeline

    strategy = get_strategy(strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found")

    async def stream():
        async for event in run_backtest_pipeline(strategy, period):
            yield event

    return EventSourceResponse(stream())


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


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def root():
    return FileResponse("frontend/index.html")


# ── Static assets ─────────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="frontend"), name="static")
