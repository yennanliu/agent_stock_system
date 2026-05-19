import asyncio
import json
import logging
from typing import AsyncGenerator

from crewai import Crew, Process

from src.agents.market_data import market_data_agent, build_market_data_task, get_cached_df
from src.agents.strategy import (
    strategy_agent,
    build_strategy_task,
    parse_strategy_response,
    extract_strategy_name,
    extract_parameters,
)
from src.agents.python_master import python_master_agent, review_and_repair
from src.agents.backtest import backtest_agent, build_backtest_task, generate_explanation
from src.tools.fetch_data import fetch_ohlcv
from src.tools.indicators import compute_indicators, market_summary
from src.tools.backtest_runner import run_backtest
from src.tools.db import save_strategy, save_code_review, save_backtest_run
from src.config import DEFAULT_CAPITAL, DATA_PERIOD

log = logging.getLogger(__name__)


def _sse(stage: str, message: str, **kwargs) -> dict:
    return {"data": json.dumps({"stage": stage, "message": message, **kwargs})}


async def run_analyze_pipeline(ticker: str) -> AsyncGenerator[dict, None]:
    """Full pipeline: data → strategy → review → backtest, yielding SSE events."""

    # ── Stage 1: Market Data ──────────────────────────────────────────────────
    yield _sse("market_data", f"Fetching market data for {ticker}…")
    await asyncio.sleep(0)
    try:
        df = await asyncio.get_event_loop().run_in_executor(
            None, lambda: compute_indicators(fetch_ohlcv(ticker, DATA_PERIOD))
        )
        summary = market_summary(df)
    except ValueError as e:
        yield _sse("error", str(e))
        return

    yield _sse("market_data", f"Market data ready. {len(df)} trading days loaded.", summary=summary)
    await asyncio.sleep(0)

    # ── Stage 2: Strategy Generation ─────────────────────────────────────────
    yield _sse("strategy", "Generating quantitative strategy…")
    await asyncio.sleep(0)

    task = build_strategy_task(ticker, summary)
    crew = Crew(
        agents=[strategy_agent],
        tasks=[task],
        process=Process.sequential,
        verbose=False,
    )
    try:
        result = await asyncio.get_event_loop().run_in_executor(None, crew.kickoff)
        raw_output = str(result)
        source_code, explanation = parse_strategy_response(raw_output)
    except Exception as e:
        yield _sse("error", f"Strategy generation failed: {e}")
        return

    strategy_name = extract_strategy_name(source_code)
    parameters = extract_parameters(source_code)
    yield _sse("strategy", f"Strategy '{strategy_name}' generated.")
    await asyncio.sleep(0)

    # ── Stage 3: Code Review ──────────────────────────────────────────────────
    yield _sse("review", f"PythonMasterAgent reviewing '{strategy_name}'…")
    await asyncio.sleep(0)

    review = await asyncio.get_event_loop().run_in_executor(
        None, review_and_repair, source_code
    )

    if not review["approved"]:
        reason = review.get("rejection_reason", "Unknown")
        yield _sse("error", f"Code review failed after {review['iterations']} attempts: {reason}")
        return

    approved_code = review["source_code"]
    yield _sse(
        "review",
        f"Code approved. Score: {review['confidence']}/100. "
        f"Iterations: {review['iterations']}. "
        f"Fixes applied: {len(review['fixes_applied'])}.",
        confidence=review["confidence"],
        iterations=review["iterations"],
    )
    await asyncio.sleep(0)

    # ── Save strategy to DB ───────────────────────────────────────────────────
    strategy_id = save_strategy(
        ticker=ticker,
        name=strategy_name,
        description=explanation[:500] if explanation else "",
        source_code=approved_code,
        parameters=parameters,
    )
    save_code_review(
        strategy_id=strategy_id,
        confidence=review["confidence"],
        issues_found=review["issues_found"],
        fixes_applied=review["fixes_applied"],
        iterations=review["iterations"],
        approved=review["approved"],
    )

    # ── Stage 4: Backtest ─────────────────────────────────────────────────────
    yield _sse("backtest", "Running backtest simulation…")
    await asyncio.sleep(0)

    try:
        bt_result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: run_backtest(approved_code, df, DEFAULT_CAPITAL)
        )
    except RuntimeError as e:
        yield _sse("error", f"Backtest failed: {e}")
        return

    narrative = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: generate_explanation(strategy_name, explanation, bt_result["metrics"]),
    )

    run_id = save_backtest_run(
        strategy_id=strategy_id,
        ticker=ticker,
        start_date=bt_result["start_date"],
        end_date=bt_result["end_date"],
        initial_capital=DEFAULT_CAPITAL,
        metrics=bt_result["metrics"],
        equity_curve=bt_result["equity_curve"],
        trade_log=bt_result["trade_log"],
        explanation=narrative,
    )

    m = bt_result["metrics"]
    yield _sse(
        "complete",
        f"Done. Return: {m['total_return_pct']}% | Sharpe: {m['sharpe']} | "
        f"Max DD: {m['max_drawdown_pct']}%",
        strategy_id=strategy_id,
        backtest_id=run_id,
    )


async def run_backtest_pipeline(strategy: dict, period: str) -> AsyncGenerator[dict, None]:
    """Re-run a saved strategy with fresh market data."""
    ticker = strategy["ticker"]
    source_code = strategy["source_code"]
    strategy_id = strategy["id"]

    yield _sse("market_data", f"Fetching fresh data for {ticker}…")
    await asyncio.sleep(0)

    try:
        df = await asyncio.get_event_loop().run_in_executor(
            None, lambda: compute_indicators(fetch_ohlcv(ticker, period))
        )
    except ValueError as e:
        yield _sse("error", str(e))
        return

    yield _sse("backtest", "Running backtest simulation…")
    await asyncio.sleep(0)

    try:
        bt_result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: run_backtest(source_code, df, DEFAULT_CAPITAL)
        )
    except RuntimeError as e:
        yield _sse("error", f"Backtest failed: {e}")
        return

    narrative = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: generate_explanation(
            strategy["name"],
            strategy.get("description", ""),
            bt_result["metrics"],
        ),
    )

    run_id = save_backtest_run(
        strategy_id=strategy_id,
        ticker=ticker,
        start_date=bt_result["start_date"],
        end_date=bt_result["end_date"],
        initial_capital=DEFAULT_CAPITAL,
        metrics=bt_result["metrics"],
        equity_curve=bt_result["equity_curve"],
        trade_log=bt_result["trade_log"],
        explanation=narrative,
    )

    m = bt_result["metrics"]
    yield _sse(
        "complete",
        f"Done. Return: {m['total_return_pct']}% | Sharpe: {m['sharpe']} | "
        f"Max DD: {m['max_drawdown_pct']}%",
        strategy_id=strategy_id,
        backtest_id=run_id,
    )
