import re
from pathlib import Path

from crewai import Agent, Task
from crewai.tools import tool
from openai import OpenAI

from src.tools.code_validator import run_all_checks
from src.config import OPENAI_API_KEY, MAX_REVIEW_ITERATIONS

_REVIEW_PROMPT = (Path(__file__).parent.parent / "prompts" / "code_review.txt").read_text()
_client = OpenAI(api_key=OPENAI_API_KEY)


# ── LLM repair call (direct OpenAI, not through CrewAI agent loop) ────────────

def _llm_repair(source_code: str, issues: list[str]) -> str:
    issues_text = "\n".join(f"- {i}" for i in issues)
    response = _client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": _REVIEW_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Issues found:\n{issues_text}\n\n"
                    f"Strategy code to fix:\n```python\n{source_code}\n```"
                ),
            },
        ],
        temperature=0.1,
    )
    raw = response.choices[0].message.content or ""
    match = re.search(r"```python\s*(.*?)```", raw, re.DOTALL)
    if not match:
        return source_code  # repair failed; return original for next check
    return match.group(1).strip()


def _extract_fixes(raw_repair_response: str) -> list[str]:
    match = re.search(r"##\s*Fixes\s*(.*)", raw_repair_response, re.DOTALL)
    if not match:
        return []
    return [
        line.lstrip("- ").strip()
        for line in match.group(1).strip().splitlines()
        if line.strip().startswith("-")
    ]


# ── Core review + repair loop ─────────────────────────────────────────────────

def review_and_repair(source_code: str) -> dict:
    """
    Run static checks and, if issues exist, ask GPT-4o to repair the code.
    Iterates up to MAX_REVIEW_ITERATIONS times.

    Returns:
        {
            "approved": bool,
            "source_code": str,
            "confidence": int (0-100),
            "issues_found": list[str],
            "fixes_applied": list[str],
            "iterations": int,
        }
    """
    all_issues: list[str] = []
    all_fixes: list[str] = []

    for iteration in range(MAX_REVIEW_ITERATIONS):
        issues = run_all_checks(source_code)
        if not issues:
            confidence = max(95 - iteration * 5, 80)
            return {
                "approved": True,
                "source_code": source_code,
                "confidence": confidence,
                "issues_found": all_issues,
                "fixes_applied": all_fixes,
                "iterations": iteration,
            }

        all_issues.extend(issues)

        # Ask LLM to repair
        raw_response = _client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": _REVIEW_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Issues found:\n"
                        + "\n".join(f"- {i}" for i in issues)
                        + f"\n\nStrategy code to fix:\n```python\n{source_code}\n```"
                    ),
                },
            ],
            temperature=0.1,
        )
        raw = raw_response.choices[0].message.content or ""
        match = re.search(r"```python\s*(.*?)```", raw, re.DOTALL)
        if match:
            source_code = match.group(1).strip()
        fixes = _extract_fixes(raw)
        all_fixes.extend(fixes)

    # Final check after last iteration
    final_issues = run_all_checks(source_code)
    if not final_issues:
        return {
            "approved": True,
            "source_code": source_code,
            "confidence": 70,
            "issues_found": all_issues,
            "fixes_applied": all_fixes,
            "iterations": MAX_REVIEW_ITERATIONS,
        }

    return {
        "approved": False,
        "source_code": source_code,
        "confidence": 0,
        "issues_found": all_issues + final_issues,
        "fixes_applied": all_fixes,
        "iterations": MAX_REVIEW_ITERATIONS,
        "rejection_reason": " | ".join(final_issues),
    }


# ── CrewAI tool wrapper (used for agent visibility in crew logs) ──────────────

@tool("review_and_repair_strategy")
def review_and_repair_tool(source_code: str) -> str:
    """Review Python strategy code for correctness and repair issues found."""
    result = review_and_repair(source_code)
    status = "APPROVED" if result["approved"] else "REJECTED"
    return (
        f"Status: {status}\n"
        f"Confidence: {result['confidence']}/100\n"
        f"Iterations: {result['iterations']}\n"
        f"Issues: {result['issues_found']}\n"
        f"Fixes: {result['fixes_applied']}"
    )


# ── Agent definition ──────────────────────────────────────────────────────────

python_master_agent = Agent(
    role="Python Master",
    goal=(
        "Ensure the generated strategy code is syntactically correct, "
        "API-conformant, and free of look-ahead bias before it runs."
    ),
    backstory=(
        "You are a principal engineer specialising in Python correctness and "
        "backtesting library internals. You catch subtle bugs — look-ahead bias, "
        "missing self.I() wrappers, forbidden imports — and fix them cleanly."
    ),
    tools=[review_and_repair_tool],
    verbose=True,
)


def build_review_task(source_code: str) -> Task:
    return Task(
        description=(
            "Review the following strategy code for correctness and repair any issues.\n\n"
            f"```python\n{source_code}\n```"
        ),
        expected_output=(
            "A review result: approved/rejected status, confidence score, "
            "list of issues found, and list of fixes applied."
        ),
        agent=python_master_agent,
    )
