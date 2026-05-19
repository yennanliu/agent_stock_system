import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from src.config import DEFAULT_CAPITAL, DATA_PERIOD
from src.tools.db import (
    init_db,
    get_strategy,
    get_backtest,
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


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def root():
    from fastapi.responses import FileResponse
    return FileResponse("frontend/index.html")


# ── Static assets ─────────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="frontend"), name="static")
