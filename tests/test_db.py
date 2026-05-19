"""Tests for SQLite persistence layer."""
import json
import sqlite3
import pytest

import src.tools.db as db_module
from src.tools.db import (
    init_db,
    save_strategy,
    save_code_review,
    save_backtest_run,
    get_strategy,
    get_backtest,
    list_strategies,
    list_runs_for_ticker,
)


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Redirect DB_PATH to a throw-away file for each test."""
    db_file = str(tmp_path / "test.db")
    monkeypatch.setattr(db_module, "DB_PATH", db_file)
    init_db()
    return db_file


# ── init_db ────────────────────────────────────────────────────────────────────

class TestInitDb:
    def test_creates_strategies_table(self, temp_db):
        con = sqlite3.connect(temp_db)
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        con.close()
        assert "strategies" in tables

    def test_creates_code_reviews_table(self, temp_db):
        con = sqlite3.connect(temp_db)
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        con.close()
        assert "code_reviews" in tables

    def test_creates_backtest_runs_table(self, temp_db):
        con = sqlite3.connect(temp_db)
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        con.close()
        assert "backtest_runs" in tables

    def test_idempotent(self):
        """Calling init_db twice should not raise."""
        init_db()
        init_db()


# ── save_strategy / get_strategy ──────────────────────────────────────────────

class TestStrategy:
    def _save(self, ticker="AAPL", name="TestStrat"):
        return save_strategy(
            ticker=ticker,
            name=name,
            description="A test strategy",
            source_code="class TestStrat(Strategy): pass",
            parameters={"n": 20, "threshold": 0.5},
        )

    def test_save_returns_integer_id(self):
        sid = self._save()
        assert isinstance(sid, int) and sid > 0

    def test_get_returns_saved_strategy(self):
        sid = self._save(ticker="NVDA", name="MyStrat")
        row = get_strategy(sid)
        assert row is not None
        assert row["ticker"] == "NVDA"
        assert row["name"] == "MyStrat"
        assert row["source_code"] == "class TestStrat(Strategy): pass"

    def test_parameters_decoded_as_dict(self):
        sid = self._save()
        row = get_strategy(sid)
        assert isinstance(row["parameters"], dict)
        assert row["parameters"]["n"] == 20

    def test_get_nonexistent_returns_none(self):
        assert get_strategy(99999) is None

    def test_multiple_strategies_get_unique_ids(self):
        id1 = self._save("AAPL", "S1")
        id2 = self._save("TSLA", "S2")
        assert id1 != id2

    def test_list_strategies_returns_all(self):
        self._save("AAPL", "S1")
        self._save("TSLA", "S2")
        rows = list_strategies()
        assert len(rows) == 2

    def test_list_strategies_newest_first(self):
        self._save("AAPL", "First")
        self._save("TSLA", "Second")
        rows = list_strategies()
        assert rows[0]["name"] == "Second"


# ── save_code_review ──────────────────────────────────────────────────────────

class TestCodeReview:
    def test_save_and_retrieve_with_strategy(self):
        sid = save_strategy("AAPL", "S", "desc", "code", {})
        save_code_review(
            strategy_id=sid,
            confidence=92,
            issues_found=["missing self.I()"],
            fixes_applied=["wrapped indicator in self.I()"],
            iterations=1,
            approved=True,
        )
        row = get_strategy(sid)
        assert row["confidence"] == 92
        assert row["approved"] == 1
        assert isinstance(row["issues_found"], list)
        assert row["issues_found"][0] == "missing self.I()"


# ── save_backtest_run / get_backtest ──────────────────────────────────────────

class TestBacktestRun:
    SAMPLE_METRICS = {
        "total_return_pct": 23.4,
        "cagr_pct": 11.2,
        "sharpe": 1.84,
        "max_drawdown_pct": -12.1,
        "win_rate_pct": 58.3,
        "num_trades": 27,
    }
    SAMPLE_EQUITY = [{"date": "2023-01-01", "equity": 10000.0}, {"date": "2023-12-31", "equity": 12340.0}]
    SAMPLE_TRADES = [{"entry_date": "2023-02-01", "exit_date": "2023-03-01", "pnl": 340.0}]

    def _save_run(self, strategy_id):
        return save_backtest_run(
            strategy_id=strategy_id,
            ticker="AAPL",
            start_date="2023-01-01",
            end_date="2023-12-31",
            initial_capital=10000.0,
            metrics=self.SAMPLE_METRICS,
            equity_curve=self.SAMPLE_EQUITY,
            trade_log=self.SAMPLE_TRADES,
            explanation="Strong performance with low drawdown.",
        )

    def test_save_returns_integer_id(self):
        sid = save_strategy("AAPL", "S", "", "code", {})
        rid = self._save_run(sid)
        assert isinstance(rid, int) and rid > 0

    def test_get_backtest_returns_row(self):
        sid = save_strategy("AAPL", "S", "", "code", {})
        rid = self._save_run(sid)
        row = get_backtest(rid)
        assert row is not None
        assert row["ticker"] == "AAPL"

    def test_metrics_decoded_as_dict(self):
        sid = save_strategy("AAPL", "S", "", "code", {})
        rid = self._save_run(sid)
        row = get_backtest(rid)
        assert isinstance(row["metrics"], dict)
        assert row["metrics"]["sharpe"] == pytest.approx(1.84)

    def test_equity_curve_decoded_as_list(self):
        sid = save_strategy("AAPL", "S", "", "code", {})
        rid = self._save_run(sid)
        row = get_backtest(rid)
        assert isinstance(row["equity_curve"], list)
        assert row["equity_curve"][0]["equity"] == 10000.0

    def test_get_nonexistent_returns_none(self):
        assert get_backtest(99999) is None


# ── list_runs_for_ticker ──────────────────────────────────────────────────────

class TestListRunsForTicker:
    def test_returns_runs_for_ticker(self):
        sid = save_strategy("NVDA", "S", "", "code", {})
        save_backtest_run(sid, "NVDA", "2023-01-01", "2023-12-31", 10000,
                          {"sharpe": 1.0}, [], [], "ok")
        rows = list_runs_for_ticker("NVDA")
        assert len(rows) == 1
        assert rows[0]["ticker"] == "NVDA"

    def test_case_insensitive_ticker(self):
        sid = save_strategy("TSLA", "S", "", "code", {})
        save_backtest_run(sid, "TSLA", "2023-01-01", "2023-12-31", 10000,
                          {"sharpe": 0.5}, [], [], "ok")
        rows = list_runs_for_ticker("tsla")
        assert len(rows) == 1

    def test_does_not_return_other_tickers(self):
        sid1 = save_strategy("AAPL", "S1", "", "code", {})
        sid2 = save_strategy("TSLA", "S2", "", "code", {})
        save_backtest_run(sid1, "AAPL", "2023-01-01", "2023-12-31", 10000, {}, [], [], "")
        save_backtest_run(sid2, "TSLA", "2023-01-01", "2023-12-31", 10000, {}, [], [], "")
        rows = list_runs_for_ticker("AAPL")
        assert all(r["ticker"] == "AAPL" for r in rows)

    def test_metrics_decoded_in_list(self):
        sid = save_strategy("META", "S", "", "code", {})
        save_backtest_run(sid, "META", "2023-01-01", "2023-12-31", 10000,
                          {"sharpe": 2.1, "total_return_pct": 40.0}, [], [], "")
        rows = list_runs_for_ticker("META")
        assert isinstance(rows[0]["metrics"], dict)
        assert rows[0]["metrics"]["sharpe"] == pytest.approx(2.1)
