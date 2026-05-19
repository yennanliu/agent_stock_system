"""Tests for the sandboxed strategy execution and backtest runner."""
import pytest
import pandas as pd
import numpy as np

from src.tools.backtest_runner import run_backtest, _load_strategy_class, _make_scope


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def synthetic_ohlcv():
    """200-day synthetic OHLCV DataFrame with enough range for indicators."""
    rng = np.random.default_rng(42)
    n = 300
    t = np.linspace(0, 6 * np.pi, n)
    close = pd.Series(100 + 20 * np.sin(t) + rng.normal(0, 0.5, n))
    return pd.DataFrame({
        "Open":   (close * (1 + rng.uniform(-0.003, 0.003, n))).values,
        "High":   (close * (1 + rng.uniform(0.001, 0.01, n))).values,
        "Low":    (close * (1 - rng.uniform(0.001, 0.01, n))).values,
        "Close":  close.values,
        "Volume": rng.integers(1_000_000, 5_000_000, n).astype(float),
    }, index=pd.date_range("2022-01-01", periods=n, freq="B"))


SMA_CROSS_STRATEGY = """
class SmaCross(Strategy):
    n_fast = 10
    n_slow = 30

    def init(self):
        close = self.data.Close
        self.fast = self.I(lambda x: pd.Series(x).rolling(self.n_fast).mean().values, close)
        self.slow = self.I(lambda x: pd.Series(x).rolling(self.n_slow).mean().values, close)

    def next(self):
        if crossover(self.fast, self.slow):
            self.buy()
        elif crossover(self.slow, self.fast):
            self.sell()
"""

RSI_STRATEGY = """
class RsiStrategy(Strategy):
    period = 14
    oversold = 35
    overbought = 65

    def init(self):
        close = self.data.Close

        def _rsi(x, p=14):
            s = pd.Series(x)
            d = s.diff()
            g = d.clip(lower=0).rolling(p).mean()
            l = (-d.clip(upper=0)).rolling(p).mean()
            return (100 - 100 / (1 + g / l.replace(0, np.nan))).values

        self.rsi = self.I(_rsi, close)

    def next(self):
        if self.rsi[-1] < self.oversold and not self.position:
            self.buy()
        elif self.rsi[-1] > self.overbought and self.position:
            self.sell()
"""


# ── _make_scope ────────────────────────────────────────────────────────────────

class TestMakeScope:
    def test_required_names_present(self):
        scope = _make_scope()
        for name in ("Strategy", "crossover", "np", "pd", "__builtins__"):
            assert name in scope, f"Missing from scope: {name}"

    def test_safe_import_blocks_os(self):
        scope = _make_scope()
        safe_import = scope["__builtins__"]["__import__"]
        with pytest.raises(ImportError, match="not allowed"):
            safe_import("os")

    def test_safe_import_blocks_subprocess(self):
        scope = _make_scope()
        safe_import = scope["__builtins__"]["__import__"]
        with pytest.raises(ImportError, match="not allowed"):
            safe_import("subprocess")

    def test_safe_import_allows_numpy(self):
        scope = _make_scope()
        safe_import = scope["__builtins__"]["__import__"]
        mod = safe_import("numpy")
        assert mod is np

    def test_safe_import_allows_pandas(self):
        scope = _make_scope()
        safe_import = scope["__builtins__"]["__import__"]
        mod = safe_import("pandas")
        assert mod is pd


# ── _load_strategy_class ───────────────────────────────────────────────────────

class TestLoadStrategyClass:
    def test_loads_valid_strategy(self):
        from backtesting import Strategy
        cls = _load_strategy_class(SMA_CROSS_STRATEGY)
        assert issubclass(cls, Strategy)
        assert cls.__name__ == "SmaCross"

    def test_raises_on_syntax_error(self):
        with pytest.raises(RuntimeError, match="failed to execute"):
            _load_strategy_class("class Broken(Strategy):\n  def init(self\n    pass")

    def test_raises_on_missing_strategy_subclass(self):
        with pytest.raises(RuntimeError, match="No Strategy subclass"):
            _load_strategy_class("x = 1 + 2")

    def test_raises_on_forbidden_import(self):
        bad = "import os\n" + SMA_CROSS_STRATEGY
        with pytest.raises((RuntimeError, ImportError)):
            _load_strategy_class(bad)

    def test_import_numpy_pandas_inside_strategy_works(self):
        code = "import numpy as np\nimport pandas as pd\n" + SMA_CROSS_STRATEGY
        from backtesting import Strategy
        cls = _load_strategy_class(code)
        assert issubclass(cls, Strategy)


# ── run_backtest ───────────────────────────────────────────────────────────────

class TestRunBacktest:
    def test_returns_expected_keys(self, synthetic_ohlcv):
        result = run_backtest(SMA_CROSS_STRATEGY, synthetic_ohlcv)
        assert "metrics" in result
        assert "equity_curve" in result
        assert "trade_log" in result
        assert "start_date" in result
        assert "end_date" in result

    def test_metrics_keys_present(self, synthetic_ohlcv):
        result = run_backtest(SMA_CROSS_STRATEGY, synthetic_ohlcv)
        m = result["metrics"]
        for key in ("total_return_pct", "cagr_pct", "sharpe", "max_drawdown_pct",
                    "win_rate_pct", "num_trades", "exposure_pct", "buy_hold_return_pct"):
            assert key in m, f"Missing metric: {key}"

    def test_equity_curve_is_list_of_dicts(self, synthetic_ohlcv):
        result = run_backtest(SMA_CROSS_STRATEGY, synthetic_ohlcv)
        eq = result["equity_curve"]
        assert isinstance(eq, list) and len(eq) > 0
        assert "date" in eq[0] and "equity" in eq[0]

    def test_equity_starts_near_initial_cash(self, synthetic_ohlcv):
        result = run_backtest(SMA_CROSS_STRATEGY, synthetic_ohlcv, initial_cash=10_000)
        first_equity = result["equity_curve"][0]["equity"]
        assert abs(first_equity - 10_000) < 500  # within 5% of start

    def test_trade_log_is_list(self, synthetic_ohlcv):
        result = run_backtest(SMA_CROSS_STRATEGY, synthetic_ohlcv)
        assert isinstance(result["trade_log"], list)

    def test_trade_log_entries_have_required_fields(self, synthetic_ohlcv):
        result = run_backtest(SMA_CROSS_STRATEGY, synthetic_ohlcv)
        for trade in result["trade_log"]:
            for field in ("entry_date", "exit_date", "pnl", "return_pct"):
                assert field in trade, f"Missing trade field: {field}"

    def test_max_drawdown_is_negative_or_zero(self, synthetic_ohlcv):
        result = run_backtest(SMA_CROSS_STRATEGY, synthetic_ohlcv)
        assert result["metrics"]["max_drawdown_pct"] <= 0

    def test_rsi_strategy_runs(self, synthetic_ohlcv):
        result = run_backtest(RSI_STRATEGY, synthetic_ohlcv)
        assert "metrics" in result

    def test_raises_on_invalid_code(self, synthetic_ohlcv):
        with pytest.raises(RuntimeError):
            run_backtest("not valid python !!!", synthetic_ohlcv)

    def test_date_range_matches_dataframe(self, synthetic_ohlcv):
        result = run_backtest(SMA_CROSS_STRATEGY, synthetic_ohlcv)
        assert result["start_date"] == str(synthetic_ohlcv.index[0].date())
        assert result["end_date"] == str(synthetic_ohlcv.index[-1].date())
