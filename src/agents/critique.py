"""
SelfCritiqueAgent — stage 5 of the pipeline.

Reads the backtest results and generates:
  1. A critique of the strategy's weaknesses.
  2. A revised strategy class that addresses those weaknesses.

The revised code is then run through the same review + backtest loop as the
original, producing a second run linked to the same strategy_id.
"""
import json
import logging
import re
from pathlib import Path

from openai import OpenAI

from src.config import OPENAI_API_KEY

log = logging.getLogger(__name__)
_client = OpenAI(api_key=OPENAI_API_KEY)

_STRATEGY_GEN_RULES = (Path(__file__).parent.parent / "prompts" / "strategy_gen.txt").read_text()

_CRITIQUE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "critique_output",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "critique": {"type": "string"},
                "revised_code": {"type": "string"},
                "changes_summary": {"type": "string"},
            },
            "required": ["critique", "revised_code", "changes_summary"],
            "additionalProperties": False,
        },
    },
}

_SYSTEM_PROMPT = f"""
You are a senior quantitative researcher performing a post-backtest critique.

You will receive:
1. The original strategy source code.
2. Backtest metrics (JSON).
3. A performance narrative.

Your task:
A) Write a concise critique (2-3 paragraphs) identifying specific weaknesses:
   - Is the Sharpe ratio too low? Why?
   - Is the drawdown excessive? What causes it?
   - Is the win rate inconsistent with the profit factor?
   - Are the parameters likely overfit?

B) Produce a REVISED strategy class that addresses those weaknesses. The revised class
   MUST follow ALL the same rules as the original strategy generation:

{_STRATEGY_GEN_RULES}

Return JSON with three fields:
- "critique": markdown text (your analysis)
- "revised_code": the raw Python class source (NO markdown fences, just the class)
- "changes_summary": one-sentence summary of the main change made
"""


def generate_critique(
    strategy_name: str,
    source_code: str,
    metrics: dict,
    narrative: str,
) -> dict:
    """
    Returns:
        {
            "critique": str,
            "revised_code": str,
            "changes_summary": str,
        }
    """
    user_msg = (
        f"Strategy: {strategy_name}\n\n"
        f"Source code:\n```python\n{source_code}\n```\n\n"
        f"Backtest metrics:\n{json.dumps(metrics, indent=2)}\n\n"
        f"Performance narrative:\n{narrative}"
    )

    response = _client.chat.completions.create(
        model="gpt-4o",
        response_format=_CRITIQUE_SCHEMA,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
        temperature=0.4,
    )

    data = json.loads(response.choices[0].message.content or "{}")

    # Strip accidental markdown fences from revised_code
    code = data.get("revised_code", "").strip()
    code = re.sub(r"^```python\s*", "", code)
    code = re.sub(r"^```\s*",        "", code)
    code = re.sub(r"\s*```$",        "", code).strip()
    data["revised_code"] = code

    return data
