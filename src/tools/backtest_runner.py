import builtins as _builtins
from typing import Any

import numpy as np
import pandas as pd
from backtesting import Backtest, Strategy
from backtesting.lib import crossover, cross, barssince, resample_apply

from src.config import DEFAULT_CAPITAL
from src.tools.ta_helpers import TA_HELPERS


# ── Safe execution scope ──────────────────────────────────────────────────────

_ALLOWED_IMPORTS = {"numpy", "pandas", "math", "statistics", "backtesting", "backtesting.lib"}
# Builtins that could escape the sandbox or cause damage
_BLOCKED_BUILTINS = frozenset({"open", "eval", "compile", "exec", "breakpoint", "__loader__", "__spec__"})


def _safe_import(name, *args, **kwargs):
    root = name.split(".")[0]
    if root not in _ALLOWED_IMPORTS and name not in _ALLOWED_IMPORTS:
        raise ImportError(f"Import of '{name}' is not allowed in strategy code.")
    return __import__(name, *args, **kwargs)


def _make_scope() -> dict[str, Any]:
    # Start with ALL Python builtins so staticmethod, classmethod, super,
    # property, etc. are available, then strip the dangerous ones.
    safe_builtins = {
        k: v for k, v in vars(_builtins).items()
        if k not in _BLOCKED_BUILTINS
    }
    safe_builtins["__import__"] = _safe_import
    scope = {
        "__builtins__": safe_builtins,
        "Strategy": Strategy,
        "np": np,
        "pd": pd,
        # backtesting.lib helpers
        "crossover": crossover,
        "cross": cross,
        "barssince": barssince,
        "resample_apply": resample_apply,
    }
    # TA helper functions (SMA, EMA, RSI, MACD, BBANDS_*, ATR, …)
    scope.update(TA_HELPERS)
    return scope


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


# ── Parameter optimisation ───────────────────────────────────────────────────

def _build_param_grid(StrategyClass: type) -> dict[str, list]:
    """Build a sensible search grid from a strategy class's numeric class attributes."""
    grid: dict[str, list] = {}
    for name, val in vars(StrategyClass).items():
        if name.startswith("_"):
            continue
        if isinstance(val, int) and val > 0:
            lo   = max(2, int(val * 0.5))
            hi   = max(lo + 2, int(val * 1.5))
            step = max(1, (hi - lo) // 4)
            candidates = list(range(lo, hi + 1, step))
            if val not in candidates:
                candidates.append(val)
            candidates = sorted(set(candidates))[:6]
            if len(candidates) > 1:
                grid[name] = candidates
        elif isinstance(val, float) and 0 < val < 200:
            factors = [0.5, 0.75, 1.0, 1.25, 1.5]
            candidates = sorted({round(val * f, 4) for f in factors})
            if len(candidates) > 1:
                grid[name] = candidates
    return grid


def optimize_backtest(
    source_code: str,
    df: pd.DataFrame,
    initial_cash: float = DEFAULT_CAPITAL,
    maximize: str = "Sharpe Ratio",
    max_tries: int = 100,
) -> dict:
    """
    Grid-search strategy parameters and return the best configuration.

    Returns:
        {
            "best_params": {name: value, ...},
            "metrics": {...},           # metrics at best params
            "maximize": str,
            "tried": int,
        }
    or {} if the strategy has no tunable parameters or optimisation fails.
    """
    StrategyClass = _load_strategy_class(source_code)
    grid = _build_param_grid(StrategyClass)
    if not grid:
        return {}

    bt = Backtest(df, StrategyClass, cash=initial_cash, commission=0.002, exclusive_orders=True)
    try:
        opt_stats = bt.optimize(
            **{k: v for k, v in grid.items()},
            maximize=maximize,
            max_tries=max_tries,
            return_heatmap=False,
        )
    except Exception as e:
        raise RuntimeError(f"Optimisation failed: {e}") from e

    # Extract which param values were used for the best run (convert numpy scalars)
    best_params: dict = {}
    for name in grid:
        try:
            val = getattr(opt_stats._strategy, name)
            best_params[name] = int(val) if isinstance(val, (int, np.integer)) else float(val)
        except AttributeError:
            pass

    return {
        "best_params": best_params,
        "metrics": _extract_metrics(opt_stats),
        "maximize": maximize,
        "tried": int(opt_stats.get("# Trades", 0)),  # proxy for tried count
        "grid_size": sum(len(v) for v in grid.values()),
    }


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

    trade_log = _trade_log(stats)

    # Price series for the prediction-vs-actual chart
    price_series = [
        {"date": str(idx.date()), "close": round(float(v), 4)}
        for idx, v in df["Close"].items()
    ]

    # Buy/sell signals derived from trade log (date only, no timestamp)
    def _date_str(v):
        return str(v)[:10] if v else ""

    signals = []
    for t in trade_log:
        if t["entry_date"]:
            signals.append({"date": _date_str(t["entry_date"]), "type": "buy",  "price": t["entry_price"]})
        if t["exit_date"]:
            signals.append({"date": _date_str(t["exit_date"]),  "type": "sell", "price": t["exit_price"]})

    # Walk-forward: in-sample (first 70%) vs out-of-sample (last 30%)
    walkforward = {}
    split = int(len(df) * 0.70)
    df_in  = df.iloc[:split]
    df_out = df.iloc[split:]
    if len(df_in) > 50 and len(df_out) > 20:
        try:
            wf_in  = Backtest(df_in,  StrategyClass, cash=initial_cash, commission=0.002, exclusive_orders=True)
            wf_out = Backtest(df_out, StrategyClass, cash=initial_cash, commission=0.002, exclusive_orders=True)
            walkforward = {
                "split_date":  str(df.index[split].date()),
                "in_sample":   _extract_metrics(wf_in.run()),
                "out_sample":  _extract_metrics(wf_out.run()),
            }
        except Exception:
            pass  # walk-forward is best-effort; don't block the full backtest result

    return {
        "metrics": _extract_metrics(stats),
        "equity_curve": _equity_series(stats),
        "trade_log": trade_log,
        "price_series": price_series,
        "signals": signals,
        "walkforward": walkforward,
        "start_date": str(df.index[0].date()),
        "end_date": str(df.index[-1].date()),
    }
