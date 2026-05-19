"""Tests for the TA helper functions exposed to LLM-generated strategies."""
import numpy as np
import pandas as pd
import pytest

from src.tools.ta_helpers import (
    SMA, EMA, RSI, MACD, MACD_SIGNAL,
    BBANDS_UPPER, BBANDS_MID, BBANDS_LOWER,
    ATR, STDEV, HIGHEST, LOWEST,
    TA_HELPERS,
)


@pytest.fixture
def close():
    rng = np.random.default_rng(0)
    return 100 + np.cumsum(rng.normal(0, 1, 200))


@pytest.fixture
def hlc(close):
    rng = np.random.default_rng(1)
    return {
        "high":  close + rng.uniform(0, 2, len(close)),
        "low":   close - rng.uniform(0, 2, len(close)),
        "close": close,
    }


# ── Return type & shape ────────────────────────────────────────────────────────

class TestReturnTypes:
    def test_all_helpers_return_ndarray(self, close, hlc):
        assert isinstance(SMA(close, 20), np.ndarray)
        assert isinstance(EMA(close, 20), np.ndarray)
        assert isinstance(RSI(close, 14), np.ndarray)
        assert isinstance(MACD(close), np.ndarray)
        assert isinstance(MACD_SIGNAL(close), np.ndarray)
        assert isinstance(BBANDS_UPPER(close, 20), np.ndarray)
        assert isinstance(BBANDS_MID(close, 20), np.ndarray)
        assert isinstance(BBANDS_LOWER(close, 20), np.ndarray)
        assert isinstance(ATR(hlc["high"], hlc["low"], hlc["close"], 14), np.ndarray)
        assert isinstance(STDEV(close, 20), np.ndarray)
        assert isinstance(HIGHEST(close, 20), np.ndarray)
        assert isinstance(LOWEST(close, 20), np.ndarray)

    def test_all_helpers_preserve_length(self, close, hlc):
        n = len(close)
        for func, args in [
            (SMA, (close, 20)), (EMA, (close, 20)), (RSI, (close, 14)),
            (MACD, (close,)), (MACD_SIGNAL, (close,)),
            (BBANDS_UPPER, (close, 20)), (BBANDS_MID, (close, 20)), (BBANDS_LOWER, (close, 20)),
            (STDEV, (close, 20)), (HIGHEST, (close, 20)), (LOWEST, (close, 20)),
        ]:
            assert len(func(*args)) == n, f"{func.__name__} broke length"
        assert len(ATR(hlc["high"], hlc["low"], hlc["close"], 14)) == n


# ── Mathematical correctness ───────────────────────────────────────────────────

class TestCorrectness:
    def test_sma_values(self):
        result = SMA(np.array([1.0, 2.0, 3.0, 4.0, 5.0]), 3)
        assert result[2] == pytest.approx(2.0)
        assert result[4] == pytest.approx(4.0)

    def test_rsi_range(self, close):
        result = RSI(close, 14)
        valid = result[~np.isnan(result)]
        assert (valid >= 0).all() and (valid <= 100).all()

    def test_rsi_strict_uptrend_is_100(self):
        s = np.arange(1, 101, dtype=float)
        result = RSI(s, 14)
        assert result[-1] == pytest.approx(100.0)

    def test_bbands_ordering(self, close):
        upper = BBANDS_UPPER(close, 20)
        mid   = BBANDS_MID(close, 20)
        lower = BBANDS_LOWER(close, 20)
        for i in range(30, len(close)):
            assert upper[i] > mid[i] > lower[i]

    def test_atr_positive(self, hlc):
        result = ATR(hlc["high"], hlc["low"], hlc["close"], 14)
        valid = result[~np.isnan(result)]
        assert (valid > 0).all()

    def test_highest_lowest_inequality(self, close):
        hi = HIGHEST(close, 20)
        lo = LOWEST(close, 20)
        valid = ~np.isnan(hi) & ~np.isnan(lo)
        assert (hi[valid] >= lo[valid]).all()

    def test_macd_minus_signal_is_histogram_like(self, close):
        """MACD line minus its signal should oscillate around 0."""
        macd = MACD(close)
        signal = MACD_SIGNAL(close)
        diff = macd - signal
        # In any non-trivial random walk this should cross zero
        valid = diff[~np.isnan(diff)]
        assert valid.min() < 0 and valid.max() > 0


# ── Registry ───────────────────────────────────────────────────────────────────

class TestRegistry:
    def test_ta_helpers_registry_complete(self):
        expected = {"SMA", "EMA", "RSI", "MACD", "MACD_SIGNAL",
                    "BBANDS_UPPER", "BBANDS_MID", "BBANDS_LOWER",
                    "ATR", "STDEV", "HIGHEST", "LOWEST"}
        assert set(TA_HELPERS.keys()) == expected

    def test_all_registry_values_are_callable(self):
        for name, func in TA_HELPERS.items():
            assert callable(func), f"{name} is not callable"


# ── End-to-end: strategy using all helpers in a backtest ──────────────────────

class TestStrategiesUsingHelpers:
    def test_strategy_using_sma_runs(self):
        from src.tools.backtest_runner import run_backtest
        n = 250
        rng = np.random.default_rng(42)
        close = 100 + np.cumsum(rng.normal(0, 1, n))
        df = pd.DataFrame({
            "Open":   close,
            "High":   close + rng.uniform(0, 1, n),
            "Low":    close - rng.uniform(0, 1, n),
            "Close":  close,
            "Volume": rng.integers(1_000_000, 2_000_000, n).astype(float),
        }, index=pd.date_range("2023-01-01", periods=n, freq="B"))

        # The exact pattern the LLM should produce
        code = """
class HelperStrat(Strategy):
    n_fast = 10
    n_slow = 30
    rsi_p = 14

    def init(self):
        close = self.data.Close
        self.sma_fast = self.I(SMA, close, self.n_fast)
        self.sma_slow = self.I(SMA, close, self.n_slow)
        self.rsi = self.I(RSI, close, self.rsi_p)
        self.atr = self.I(ATR, self.data.High, self.data.Low, self.data.Close, 14)

    def next(self):
        if crossover(self.sma_fast, self.sma_slow):
            self.buy()
        elif crossover(self.sma_slow, self.sma_fast):
            self.sell()
"""
        result = run_backtest(code, df)
        assert "metrics" in result
        assert result["metrics"]["num_trades"] >= 0

    def test_sma_helper_preserves_data_length(self, close):
        """The exact bug: backtesting.py requires indicator length == data length."""
        result = SMA(close, 20)
        assert len(result) == len(close), (
            f"SMA broke length contract: input={len(close)}, output={len(result)}"
        )

    def test_strategy_using_bbands_runs(self):
        from src.tools.backtest_runner import run_backtest
        n = 250
        rng = np.random.default_rng(7)
        close = 100 + np.cumsum(rng.normal(0, 1, n))
        df = pd.DataFrame({
            "Open":   close,
            "High":   close + rng.uniform(0, 1, n),
            "Low":    close - rng.uniform(0, 1, n),
            "Close":  close,
            "Volume": rng.integers(1_000_000, 2_000_000, n).astype(float),
        }, index=pd.date_range("2023-01-01", periods=n, freq="B"))

        code = """
class BbandsStrat(Strategy):
    n = 20

    def init(self):
        close = self.data.Close
        self.upper = self.I(BBANDS_UPPER, close, self.n)
        self.lower = self.I(BBANDS_LOWER, close, self.n)

    def next(self):
        if self.data.Close[-1] < self.lower[-1]:
            self.buy()
        elif self.data.Close[-1] > self.upper[-1]:
            self.sell()
"""
        result = run_backtest(code, df)
        assert "metrics" in result
