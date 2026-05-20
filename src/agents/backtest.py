import json
from pathlib import Path

from crewai import Agent, Task
from crewai.tools import tool
from openai import OpenAI

from src.tools.backtest_runner import run_backtest
from src.config import OPENAI_API_KEY

_EXPLAIN_PROMPT = (Path(__file__).parent.parent / "prompts" / "result_explain.txt").read_text()
_client = OpenAI(api_key=OPENAI_API_KEY)


def generate_explanation(strategy_name: str, description: str, metrics: dict) -> str:
    response = _client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": _EXPLAIN_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Strategy: {strategy_name}\n"
                    f"Description: {description}\n\n"
                    f"Metrics:\n{json.dumps(metrics, indent=2)}"
                ),
            },
        ],
        temperature=0.3,
    )
    return response.choices[0].message.content or ""


@tool("run_and_explain_backtest")
def run_and_explain_tool(source_code: str, ticker: str, strategy_description: str = "") -> str:  # noqa: unused-arg
    """Run a backtest for a strategy and return metrics summary."""
    from src.agents.market_data import get_cached_df
    from src.tools.fetch_data import fetch_ohlcv
    from src.tools.indicators import compute_indicators
    from src.config import DATA_PERIOD

    df = get_cached_df(ticker)
    if df is None:
        df = compute_indicators(fetch_ohlcv(ticker, DATA_PERIOD))

    result = run_backtest(source_code, df)
    m = result["metrics"]
    return (
        f"Backtest complete.\n"
        f"Total Return: {m['total_return_pct']}% | CAGR: {m['cagr_pct']}%\n"
        f"Sharpe: {m['sharpe']} | Max DD: {m['max_drawdown_pct']}%\n"
        f"Win Rate: {m['win_rate_pct']}% | Trades: {m['num_trades']}"
    )


backtest_agent = Agent(
    role="Backtest Analyst",
    goal=(
        "Execute the approved trading strategy, compute performance metrics, "
        "and provide a clear interpretation of the results."
    ),
    backstory=(
        "You are a systematic trading analyst who specialises in strategy evaluation. "
        "You interpret backtest statistics with nuance, understanding the difference "
        "between genuine edge and curve-fitting."
    ),
    tools=[run_and_explain_tool],
    verbose=True,
)


def build_backtest_task(ticker: str, source_code: str, strategy_description: str = "") -> Task:  # noqa: unused-arg
    return Task(
        description=(
            f"Run a backtest for the following strategy on {ticker}. "
            "Report the key performance metrics.\n\n"
            f"Strategy code:\n```python\n{source_code}\n```"
        ),
        expected_output=(
            "A summary of backtest metrics: total return, CAGR, Sharpe ratio, "
            "max drawdown, win rate, and number of trades."
        ),
        agent=backtest_agent,
    )
