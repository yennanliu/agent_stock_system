import re
from pathlib import Path

from crewai import Agent, Task


# ── Response parser ───────────────────────────────────────────────────────────

class ParseError(Exception):
    pass


def parse_strategy_response(raw: str) -> tuple[str, str]:
    """Extract (source_code, explanation) from an LLM response."""
    code_match = re.search(r"```python\s*(.*?)```", raw, re.DOTALL)
    if not code_match:
        raise ParseError("No ```python ... ``` block found in strategy response.")
    source_code = code_match.group(1).strip()

    expl_match = re.search(r"##\s*Explanation\s*(.*)", raw, re.DOTALL)
    explanation = expl_match.group(1).strip() if expl_match else ""

    return source_code, explanation


def extract_strategy_name(source_code: str) -> str:
    match = re.search(r"class\s+(\w+)\s*\(", source_code)
    return match.group(1) if match else "GeneratedStrategy"


def extract_parameters(source_code: str) -> dict:
    """Pull class-level numeric parameter defaults from the strategy class."""
    params = {}
    for match in re.finditer(r"^\s{4}(\w+)\s*=\s*([\d.]+)", source_code, re.MULTILINE):
        name, value = match.group(1), match.group(2)
        if name not in ("__", ) and not name.startswith("_"):
            try:
                params[name] = float(value) if "." in value else int(value)
            except ValueError:
                pass
    return params


# ── Agent ─────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = Path(__file__).parent.parent / "prompts" / "strategy_gen.txt"

strategy_agent = Agent(
    role="Quantitative Strategy Developer",
    goal=(
        "Design and implement a backtesting.py-compatible Strategy class for a "
        "given stock, based on the provided market summary."
    ),
    backstory=(
        "You are a senior quant developer with 15 years of experience building "
        "systematic trading strategies. You write clean, correct Python that runs "
        "the first time without modification. You follow the backtesting.py API exactly."
    ),
    system_template=_SYSTEM_PROMPT.read_text() if _SYSTEM_PROMPT.exists() else None,
    verbose=True,
)


def build_strategy_task(ticker: str, market_sum: str) -> Task:
    return Task(
        description=(
            f"Design a quantitative trading strategy for {ticker}.\n\n"
            f"Market summary:\n{market_sum}\n\n"
            "Follow the system instructions exactly. Output one ```python``` block "
            "with the Strategy class, then a ## Explanation section."
        ),
        expected_output=(
            "A ```python``` code block containing a Strategy subclass, "
            "followed by a ## Explanation markdown section."
        ),
        agent=strategy_agent,
    )
