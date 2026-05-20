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
    generate_strategy_direct,
    extract_strategy_name,
    extract_parameters,
)
from src.agents.python_master import python_master_agent, review_and_repair
from src.agents.backtest import backtest_agent, build_backtest_task, generate_explanation
from src.agents.critique import generate_critique
from src.tools.fetch_data import fetch_ohlcv
from src.tools.indicators import compute_indicators, market_summary
from src.tools.backtest_runner import run_backtest
from src.tools.db import save_strategy, save_code_review, save_backtest_run
from src.config import DEFAULT_CAPITAL, DATA_PERIOD

log = logging.getLogger(__name__)


def _sse(stage: str, message: str, **kwargs) -> dict:
    return {"data": json.dumps({"stage": stage, "message": message, **kwargs})}


async def run_analyze_pipeline(
    ticker: str,
    strategy_type: str = "auto",
    indicators: str = "auto",
    period: str = DATA_PERIOD,
) -> AsyncGenerator[dict, None]:
    """Full pipeline: data → strategy → review → backtest, yielding SSE events."""

    # ── Stage 1: Market Data ──────────────────────────────────────────────────
    yield _sse("market_data", f"Fetching market data for {ticker} ({period})…")
    await asyncio.sleep(0)
    try:
        df = await asyncio.get_event_loop().run_in_executor(
            None, lambda: compute_indicators(fetch_ohlcv(ticker, period))
        )
        summary = market_summary(df)
    except ValueError as e:
        yield _sse("error", str(e))
        return

    yield _sse("market_data", f"Market data ready. {len(df)} trading days loaded.", summary=summary)
    await asyncio.sleep(0)

    # ── Stage 2: Strategy Generation (structured output, no regex parsing) ───
    yield _sse("strategy", "Generating quantitative strategy…")
    await asyncio.sleep(0)

    source_code, explanation = None, ""
    last_err = None
    for attempt in range(1, 4):
        if attempt > 1:
            yield _sse("strategy", f"Retrying strategy generation (attempt {attempt}/3)…")
            await asyncio.sleep(0)
        try:
            source_code, explanation = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: generate_strategy_direct(
                    ticker, summary,
                    strategy_type=strategy_type,
                    indicators=indicators,
                ),
            )
            break
        except Exception as e:
            last_err = e
            log.warning("Strategy generation attempt %d failed: %s", attempt, e)

    if source_code is None:
        yield _sse("error", f"Strategy generation failed after 3 attempts: {last_err}")
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
        source_code=approved_code,
        raw_df=df,
        price_series=bt_result["price_series"],
        signals=bt_result["signals"],
        walkforward=bt_result.get("walkforward"),
    )

    m = bt_result["metrics"]
    yield _sse(
        "complete",
        f"Done. Return: {m['total_return_pct']}% | Sharpe: {m['sharpe']} | "
        f"Max DD: {m['max_drawdown_pct']}%",
        strategy_id=strategy_id,
        backtest_id=run_id,
    )

    # ── Stage 5: Self-Critique & Revised Strategy ─────────────────────────────
    yield _sse("critique", "SelfCritiqueAgent analysing results and generating improvement…")
    await asyncio.sleep(0)

    try:
        critique_result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: generate_critique(strategy_name, approved_code, m, narrative),
        )
    except Exception as e:
        log.warning("Critique generation failed (non-fatal): %s", e)
        yield _sse("critique", f"Critique skipped: {e}")
        return

    yield _sse(
        "critique",
        f"Critique complete. Running revised strategy: {critique_result.get('changes_summary', '')}",
        critique=critique_result["critique"],
        changes_summary=critique_result.get("changes_summary", ""),
    )
    await asyncio.sleep(0)

    revised_code = critique_result.get("revised_code", "")
    if not revised_code:
        return

    # Review the revised code
    revised_review = await asyncio.get_event_loop().run_in_executor(
        None, review_and_repair, revised_code
    )
    if not revised_review["approved"]:
        yield _sse("critique", "Revised strategy failed code review — skipping.")
        return

    revised_approved = revised_review["source_code"]

    # Backtest the revised strategy
    try:
        revised_bt = await asyncio.get_event_loop().run_in_executor(
            None, lambda: run_backtest(revised_approved, df, DEFAULT_CAPITAL)
        )
    except RuntimeError as e:
        yield _sse("critique", f"Revised backtest failed: {e}")
        return

    revised_name     = extract_strategy_name(revised_approved) or f"{strategy_name}_Revised"
    revised_params   = extract_parameters(revised_approved)
    revised_narrative = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: generate_explanation(revised_name, critique_result["critique"], revised_bt["metrics"]),
    )

    revised_sid = save_strategy(
        ticker=ticker,
        name=revised_name,
        description=critique_result["critique"][:500],
        source_code=revised_approved,
        parameters=revised_params,
    )
    save_code_review(
        strategy_id=revised_sid,
        confidence=revised_review["confidence"],
        issues_found=revised_review["issues_found"],
        fixes_applied=revised_review["fixes_applied"],
        iterations=revised_review["iterations"],
        approved=revised_review["approved"],
    )
    revised_run_id = save_backtest_run(
        strategy_id=revised_sid,
        ticker=ticker,
        start_date=revised_bt["start_date"],
        end_date=revised_bt["end_date"],
        initial_capital=DEFAULT_CAPITAL,
        metrics=revised_bt["metrics"],
        equity_curve=revised_bt["equity_curve"],
        trade_log=revised_bt["trade_log"],
        explanation=revised_narrative,
        source_code=revised_approved,
        raw_df=df,
        price_series=revised_bt["price_series"],
        signals=revised_bt["signals"],
        walkforward=revised_bt.get("walkforward"),
    )

    rm = revised_bt["metrics"]
    yield _sse(
        "critique_complete",
        f"Revised strategy done. Return: {rm['total_return_pct']}% | Sharpe: {rm['sharpe']}",
        strategy_id=revised_sid,
        backtest_id=revised_run_id,
        original_backtest_id=run_id,
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
        source_code=source_code,
        raw_df=df,
        price_series=bt_result["price_series"],
        signals=bt_result["signals"],
        walkforward=bt_result.get("walkforward"),
    )

    m = bt_result["metrics"]
    yield _sse(
        "complete",
        f"Done. Return: {m['total_return_pct']}% | Sharpe: {m['sharpe']} | "
        f"Max DD: {m['max_drawdown_pct']}%",
        strategy_id=strategy_id,
        backtest_id=run_id,
    )
