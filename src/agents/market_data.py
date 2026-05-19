import json
import pandas as pd
from crewai import Agent, Task
from crewai.tools import tool

from src.tools.fetch_data import fetch_ohlcv
from src.tools.indicators import compute_indicators, market_summary
from src.config import DATA_PERIOD


# ── CrewAI tools ──────────────────────────────────────────────────────────────

_df_cache: dict[str, pd.DataFrame] = {}


@tool("fetch_market_data")
def fetch_market_data_tool(ticker: str) -> str:
    """Fetch OHLCV data and compute technical indicators for a stock ticker.
    Returns a market summary string."""
    df = fetch_ohlcv(ticker, DATA_PERIOD)
    df = compute_indicators(df)
    _df_cache[ticker] = df
    return market_summary(df)


def get_cached_df(ticker: str) -> pd.DataFrame | None:
    return _df_cache.get(ticker)


# ── Agent definition ──────────────────────────────────────────────────────────

market_data_agent = Agent(
    role="Market Data Analyst",
    goal=(
        "Fetch OHLCV price data and technical indicators for a given stock ticker, "
        "then produce a compact market summary that a strategy developer can act on."
    ),
    backstory=(
        "You are a systematic quantitative analyst with deep expertise in market "
        "microstructure and technical analysis. You prepare clean, concise data "
        "summaries that downstream strategy generators rely on."
    ),
    tools=[fetch_market_data_tool],
    verbose=True,
)


def build_market_data_task(ticker: str) -> Task:
    return Task(
        description=f"Fetch market data and compute technical indicators for {ticker}. "
                    f"Return the full market summary.",
        expected_output="A multi-line market summary string covering trend, volatility, RSI, volume, and available indicators.",
        agent=market_data_agent,
    )
