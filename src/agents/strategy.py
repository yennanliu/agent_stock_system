import json
import re
from pathlib import Path

from crewai import Agent, LLM, Task
from openai import OpenAI

from src.config import OPENAI_API_KEY


# ── Response parser ───────────────────────────────────────────────────────────

class ParseError(Exception):
    pass


def parse_strategy_response(raw: str) -> tuple[str, str]:
    """Extract (source_code, explanation) from an LLM response.

    Tries several fallback patterns in order:
    1. ```python ... ```   (ideal)
    2. ``` ... ```         (fence without language tag)
    3. Bare class definition starting with 'class ... (Strategy)'
    """
    # 1. Fenced with python tag
    m = re.search(r"```python\s*(.*?)```", raw, re.DOTALL)
    if not m:
        # 2. Any fenced block
        m = re.search(r"```\s*(class\s+\w.*?)```", raw, re.DOTALL)
    if not m:
        # 3. Raw class body — find first 'class ... (Strategy):' and take everything after
        m = re.search(r"(class\s+\w+\s*\(Strategy\).*)", raw, re.DOTALL)

    if not m:
        raise ParseError("No ```python ... ``` block found in strategy response.")

    source_code = m.group(1).strip()

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

_llm = LLM(model="gpt-4o", api_key=OPENAI_API_KEY)
_direct_client = OpenAI(api_key=OPENAI_API_KEY)

_STRUCTURED_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "strategy_output",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "explanation": {"type": "string"},
            },
            "required": ["code", "explanation"],
            "additionalProperties": False,
        },
    },
}

strategy_agent = Agent(
    role="Quantitative Strategy Developer",
    llm=_llm,
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


def _recent_strategy_names(ticker: str, limit: int = 5) -> list[str]:
    """Return names of the most recent strategies for this ticker (for diversity prompt)."""
    try:
        from src.tools.db import _conn  # local import to avoid circular at module load
        with _conn() as con:
            rows = con.execute(
                "SELECT name FROM strategies WHERE ticker=? ORDER BY created_at DESC, id DESC LIMIT ?",
                (ticker.upper(), limit),
            ).fetchall()
        return [r["name"] for r in rows]
    except Exception:
        return []


def generate_strategy_direct(
    ticker: str,
    market_sum: str,
    strategy_type: str = "auto",
    indicators: str = "auto",
) -> tuple[str, str]:
    """Generate strategy via OpenAI structured output — eliminates regex parsing."""
    rules = _SYSTEM_PROMPT.read_text() if _SYSTEM_PROMPT.exists() else ""

    system_msg = (
        rules
        + "\n\nIMPORTANT: Return ONLY valid JSON matching the schema — do NOT wrap code in "
        "markdown fences inside the JSON string. The 'code' field must contain the raw Python "
        "class source only (no ```python``` wrapper). The 'explanation' field is markdown text."
    )

    preference_lines = []
    if strategy_type and strategy_type != "auto":
        preference_lines.append(f"Strategy type requested: {strategy_type}")
    if indicators and indicators != "auto":
        preference_lines.append(f"Preferred indicators: {indicators}")
    pref_block = ("\nUSER PREFERENCES (must be followed):\n" + "\n".join(preference_lines)) if preference_lines else ""

    recent = _recent_strategy_names(ticker)
    diversity_block = (
        "\nDIVERSITY REQUIREMENT: The following strategies have already been generated for "
        f"this ticker — generate something meaningfully different (different logic, different "
        f"indicators, or different regime approach):\n"
        + "\n".join(f"  - {n}" for n in recent)
    ) if recent else ""

    user_msg = (
        f"Design a strategy for: {ticker}\n\nMarket summary:\n{market_sum}"
        f"{pref_block}{diversity_block}"
    )

    response = _direct_client.chat.completions.create(
        model="gpt-4o",
        response_format=_STRUCTURED_SCHEMA,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user",   "content": user_msg},
        ],
        temperature=0.3,
    )
    data = json.loads(response.choices[0].message.content or "{}")
    code = data.get("code", "").strip()
    explanation = data.get("explanation", "").strip()
    if not code:
        raise ParseError("Structured output returned empty 'code' field.")
    # Strip accidental markdown fences the model may still include
    code = re.sub(r"^```python\s*", "", code)
    code = re.sub(r"^```\s*", "", code)
    code = re.sub(r"\s*```$", "", code).strip()
    return code, explanation


def build_strategy_task(
    ticker: str,
    market_sum: str,
    strategy_type: str = "auto",
    indicators: str = "auto",
) -> Task:
    rules = _SYSTEM_PROMPT.read_text() if _SYSTEM_PROMPT.exists() else ""

    preference_lines = []
    if strategy_type and strategy_type != "auto":
        preference_lines.append(f"Strategy type requested: {strategy_type}")
    if indicators and indicators != "auto":
        preference_lines.append(f"Preferred indicators: {indicators}")
    preferences = (
        "\nUSER PREFERENCES (must be followed):\n" + "\n".join(preference_lines) + "\n"
        if preference_lines else ""
    )

    return Task(
        description=(
            f"{rules}\n\n"
            f"---\n"
            f"NOW DESIGN A STRATEGY FOR: {ticker}\n\n"
            f"Market summary:\n{market_sum}\n"
            f"{preferences}\n"
            "Output exactly one ```python``` code block with the Strategy class, "
            "then a ## Explanation section."
        ),
        expected_output=(
            "A ```python``` code block containing a Strategy subclass, "
            "followed by a ## Explanation markdown section."
        ),
        agent=strategy_agent,
    )
