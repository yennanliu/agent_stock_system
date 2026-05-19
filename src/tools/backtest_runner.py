import traceback
from typing import Any

import numpy as np
import pandas as pd
from backtesting import Backtest, Strategy
from backtesting.lib import crossover

from src.config import DEFAULT_CAPITAL


# ── Safe execution scope ──────────────────────────────────────────────────────

_ALLOWED_IMPORTS = {"numpy", "pandas", "math", "statistics", "backtesting", "backtesting.lib"}


def _safe_import(name, *args, **kwargs):
    root = name.split(".")[0]
    if root not in _ALLOWED_IMPORTS and name not in _ALLOWED_IMPORTS:
        raise ImportError(f"Import of '{name}' is not allowed in strategy code.")
    return __import__(name, *args, **kwargs)


def _make_scope() -> dict[str, Any]:
    return {
        "__builtins__": {
            "__build_class__": __build_class__,
            "__name__": __name__,
            "__import__": _safe_import,
            # standard safe builtins strategies may need
            "abs": abs, "round": round, "min": min, "max": max,
            "len": len, "range": range, "enumerate": enumerate,
            "zip": zip, "map": map, "filter": filter,
            "list": list, "dict": dict, "tuple": tuple, "set": set,
            "int": int, "float": float, "str": str, "bool": bool,
            "isinstance": isinstance, "hasattr": hasattr,
            "print": print,  # useful for debugging generated code
            "True": True, "False": False, "None": None,
        },
        "Strategy": Strategy,
        "crossover": crossover,
        "np": np,
        "pd": pd,
    }


def _load_strategy_class(source_code: str) -> type:
    scope = _make_scope()
    try:
        exec(compile(source_code, "<strategy>", "exec"), scope)
    except Exception as e:
        raise RuntimeError(f"Strategy code failed to execute: {e}") from e

    for obj in scope.values():
        try:
            if (
                isinstance(obj, type)
                and issubclass(obj, Strategy)
                and obj is not Strategy
            ):
                return obj
        except TypeError:
            continue
    raise RuntimeError("No Strategy subclass found in the generated code.")


# ── Metrics extraction ────────────────────────────────────────────────────────

def _extract_metrics(stats: pd.Series) -> dict:
    def safe(key: str, default=None):
        val = stats.get(key, default)
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return default
        return float(val) if isinstance(val, (int, float, np.number)) else val

    cagr = safe("Return [%]", 0) / 100
    max_dd = safe("Max. Drawdown [%]", 0) / 100
    calmar = round(cagr / abs(max_dd), 3) if max_dd != 0 else None

    return {
        "total_return_pct": round(safe("Return [%]", 0), 2),
        "cagr_pct": round(safe("Return (Ann.) [%]", 0), 2),
        "sharpe": round(safe("Sharpe Ratio", 0), 3),
        "max_drawdown_pct": round(safe("Max. Drawdown [%]", 0), 2),
        "win_rate_pct": round(safe("Win Rate [%]", 0), 2),
        "profit_factor": round(safe("Profit Factor", 0) or 0, 3),
        "calmar": calmar,
        "num_trades": int(safe("# Trades", 0)),
        "exposure_pct": round(safe("Exposure Time [%]", 0), 2),
        "buy_hold_return_pct": round(safe("Buy & Hold Return [%]", 0), 2),
    }


def _equity_series(stats: pd.Series) -> list[dict]:
    eq = stats["_equity_curve"]["Equity"]
    return [
        {"date": str(idx.date()), "equity": round(float(v), 2)}
        for idx, v in eq.items()
    ]


def _trade_log(stats: pd.Series) -> list[dict]:
    trades = stats["_trades"]
    if trades.empty:
        return []
    log = []
    for _, row in trades.iterrows():
        log.append(
            {
                "entry_date": str(row.get("EntryTime", "")[:10] if hasattr(row.get("EntryTime", ""), "__getitem__") else row.get("EntryTime", "")),
                "exit_date": str(row.get("ExitTime", "")[:10] if hasattr(row.get("ExitTime", ""), "__getitem__") else row.get("ExitTime", "")),
                "entry_price": round(float(row.get("EntryPrice", 0)), 4),
                "exit_price": round(float(row.get("ExitPrice", 0)), 4),
                "size": int(row.get("Size", 0)),
                "pnl": round(float(row.get("PnL", 0)), 2),
                "return_pct": round(float(row.get("ReturnPct", 0)) * 100, 2),
                "bars_held": int(row.get("Duration", pd.Timedelta(0)).days if hasattr(row.get("Duration", 0), "days") else 0),
            }
        )
    return log


# ── Public API ────────────────────────────────────────────────────────────────

def run_backtest(
    source_code: str,
    df: pd.DataFrame,
    initial_cash: float = DEFAULT_CAPITAL,
) -> dict:
    """Execute an approved strategy class and return structured results."""
    StrategyClass = _load_strategy_class(source_code)

    bt = Backtest(
        df,
        StrategyClass,
        cash=initial_cash,
        commission=0.002,
        exclusive_orders=True,
    )
    try:
        stats = bt.run()
    except Exception as e:
        raise RuntimeError(f"Backtest simulation failed: {e}") from e

    return {
        "metrics": _extract_metrics(stats),
        "equity_curve": _equity_series(stats),
        "trade_log": _trade_log(stats),
        "start_date": str(df.index[0].date()),
        "end_date": str(df.index[-1].date()),
    }
