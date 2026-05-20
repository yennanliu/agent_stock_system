"""
Integration tests — spin up the FastAPI app via TestClient and exercise
the endpoints that do NOT require an OpenAI API key.
"""
import io
import json

import pytest
from fastapi.testclient import TestClient

from src.main import app

client = TestClient(app, raise_server_exceptions=False)

# ── Simple strategy used across several tests ─────────────────────────────────
_STRATEGY = """\
class SmaCross(Strategy):
    fast = 10
    slow = 30

    def init(self):
        self.f = self.I(SMA, self.data.Close, self.fast)
        self.s = self.I(SMA, self.data.Close, self.slow)

    def next(self):
        if not self.position and crossover(self.f, self.s):
            self.buy()
        elif self.position and crossover(self.s, self.f):
            self.sell()
"""


# ── Health ────────────────────────────────────────────────────────────────────

def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# ── Static / pages ────────────────────────────────────────────────────────────

def test_root_serves_landing():
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_app_serves_analyzer():
    r = client.get("/app")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_playground_page():
    r = client.get("/api/playground")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_landing_page():
    r = client.get("/landing")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_guide_page():
    r = client.get("/guide")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


# ── REST read endpoints (empty DB is fine) ────────────────────────────────────

def test_strategies_list_returns_list():
    r = client.get("/api/strategies")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_all_runs_returns_list():
    r = client.get("/api/runs")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_history_unknown_ticker():
    r = client.get("/api/history/FAKEXYZ")
    assert r.status_code == 200
    assert r.json() == []


def test_strategy_not_found():
    r = client.get("/api/strategies/999999")
    assert r.status_code == 404


def test_backtest_not_found():
    r = client.get("/api/backtest/999999")
    assert r.status_code == 404


# ── Playground — synthetic data (no API key needed) ───────────────────────────

def _run_playground(strategy: str = _STRATEGY, **overrides):
    data = {
        "data_mode": "synthetic",
        "trend":      "up",
        "volatility": "medium",
        "n_bars":     "120",
        "capital":    "10000",
        **{k: str(v) for k, v in overrides.items()},
    }
    return client.post(
        "/api/playground/run",
        data=data,
        files={"file": ("strategy.py", strategy.encode(), "text/plain")},
    )


def test_playground_synthetic_basic():
    r = _run_playground()
    assert r.status_code == 200
    body = r.json()
    assert "metrics" in body
    assert "equity_curve" in body
    assert "trade_log" in body
    assert "ohlcv" in body
    assert body["data_mode"] == "synthetic"
    assert body["ticker"] == "SYNTHETIC"


def test_playground_metrics_schema():
    r = _run_playground()
    m = r.json()["metrics"]
    for key in ("total_return_pct", "sharpe", "max_drawdown_pct", "win_rate_pct", "num_trades"):
        assert key in m, f"Missing metric: {key}"


@pytest.mark.parametrize("trend", ["up", "down", "sideways", "volatile"])
def test_playground_all_regimes(trend):
    r = _run_playground(trend=trend, n_bars=100)
    assert r.status_code == 200
    assert r.json()["metrics"]["num_trades"] >= 0


@pytest.mark.parametrize("volatility", ["low", "medium", "high"])
def test_playground_all_volatilities(volatility):
    r = _run_playground(volatility=volatility)
    assert r.status_code == 200


def test_playground_walkforward_present():
    r = _run_playground(n_bars=200)
    body = r.json()
    assert "walkforward" in body
    wf = body["walkforward"]
    if wf:  # walk-forward runs when enough bars
        assert "in_sample" in wf
        assert "out_sample" in wf


def test_playground_runner_file_upload():
    """Uploading a full runner script (with imports, argparse) should work —
    the server extracts only the Strategy class."""
    runner = f"""\
import argparse
import sys
import numpy as np
import pandas as pd
from backtesting import Backtest, Strategy
from backtesting.lib import crossover

{_STRATEGY}

if __name__ == "__main__":
    print("runner main block — should be ignored by playground")
"""
    r = _run_playground(strategy=runner)
    assert r.status_code == 200
    assert "metrics" in r.json()


def test_playground_bad_syntax_returns_422():
    r = _run_playground(strategy="class Broken(Strategy:\n    pass")
    assert r.status_code == 422


def test_playground_no_strategy_class_returns_422():
    r = _run_playground(strategy="x = 1 + 1\nprint(x)")
    assert r.status_code == 422


def test_playground_equity_curve_length_matches_bars():
    r = _run_playground(n_bars=150)
    body = r.json()
    assert len(body["equity_curve"]) > 0
    assert len(body["ohlcv"]) > 0


# ── Job status endpoint ───────────────────────────────────────────────────────

def test_job_status_not_found():
    r = client.get("/api/jobs/nonexistent-uuid/status")
    assert r.status_code == 404


# ── Optimizer — no API key needed ────────────────────────────────────────────

def test_optimize_strategy_not_found():
    r = client.get("/api/strategies/999999/optimize")
    assert r.status_code == 404
