"""Tests for pure-pandas indicator calculations."""
import numpy as np
import pandas as pd
import pytest

from src.tools.indicators import (
    _sma, _ema, _rsi, _macd, _bollinger, _atr,
    compute_indicators, market_summary,
)


@pytest.fixture
def price_series():
    """Deterministic synthetic close price: sine wave trend + noise."""
    rng = np.random.default_rng(42)
    n = 200
    t = np.linspace(0, 4 * np.pi, n)
    prices = 100 + 20 * np.sin(t) + rng.normal(0, 1, n)
    return pd.Series(prices, name="Close")


@pytest.fixture
def ohlcv_df(price_series):
    """Minimal OHLCV DataFrame derived from the price series."""
    c = price_series.values  # use .values to avoid index misalignment
    rng = np.random.default_rng(7)
    n = len(c)
    df = pd.DataFrame({
        "Open":   c * (1 + rng.uniform(-0.005, 0.005, n)),
        "High":   c * (1 + rng.uniform(0.001, 0.015, n)),
        "Low":    c * (1 - rng.uniform(0.001, 0.015, n)),
        "Close":  c,
        "Volume": rng.integers(1_000_000, 5_000_000, n).astype(float),
    }, index=pd.date_range("2023-01-01", periods=n, freq="B"))
    return df


# ── SMA ───────────────────────────────────────────────────────────────────────

class TestSMA:
    def test_length_preserved(self, price_series):
        result = _sma(price_series, 20)
        assert len(result) == len(price_series)

    def test_first_n_minus_1_are_nan(self, price_series):
        period = 20
        result = _sma(price_series, period)
        assert result.iloc[:period - 1].isna().all()

    def test_values_correct(self):
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = _sma(s, 3)
        assert result.iloc[2] == pytest.approx(2.0)
        assert result.iloc[3] == pytest.approx(3.0)
        assert result.iloc[4] == pytest.approx(4.0)

    def test_different_periods(self, price_series):
        sma20 = _sma(price_series, 20)
        sma50 = _sma(price_series, 50)
        # SMA50 has more NaN at the start
        assert sma50.isna().sum() > sma20.isna().sum()


# ── EMA ───────────────────────────────────────────────────────────────────────

class TestEMA:
    def test_length_preserved(self, price_series):
        assert len(_ema(price_series, 12)) == len(price_series)

    def test_no_nan_after_first(self, price_series):
        result = _ema(price_series, 12)
        # EMA with adjust=False starts from first value — no NaN
        assert not result.isna().any()

    def test_ema_reacts_faster_than_sma(self, price_series):
        # After a sharp upward spike, EMA should be higher than SMA
        s = price_series.copy()
        s.iloc[-1] = s.iloc[-1] * 2  # spike
        ema = _ema(s, 12)
        sma = _sma(s, 12)
        assert ema.iloc[-1] > sma.iloc[-1]


# ── RSI ───────────────────────────────────────────────────────────────────────

class TestRSI:
    def test_range_0_to_100(self, price_series):
        result = _rsi(price_series, 14).dropna()
        assert (result >= 0).all() and (result <= 100).all()

    def test_uptrend_rsi_above_50(self):
        """Strictly rising prices should give RSI near 100."""
        s = pd.Series(range(1, 101), dtype=float)
        result = _rsi(s, 14).dropna()
        assert result.iloc[-1] > 90

    def test_downtrend_rsi_below_50(self):
        """Strictly falling prices should give RSI near 0."""
        s = pd.Series(range(100, 0, -1), dtype=float)
        result = _rsi(s, 14).dropna()
        assert result.iloc[-1] < 10

    def test_length_preserved(self, price_series):
        assert len(_rsi(price_series, 14)) == len(price_series)


# ── MACD ──────────────────────────────────────────────────────────────────────

class TestMACD:
    def test_returns_three_series(self, price_series):
        macd, signal, hist = _macd(price_series)
        assert len(macd) == len(price_series)
        assert len(signal) == len(price_series)
        assert len(hist) == len(price_series)

    def test_histogram_is_macd_minus_signal(self, price_series):
        macd, signal, hist = _macd(price_series)
        diff = (macd - signal).dropna()
        hist_clean = hist.dropna()
        pd.testing.assert_series_equal(diff, hist_clean, check_names=False)

    def test_macd_crosses_zero_in_oscillating_series(self):
        """A sine-wave price should cause MACD to oscillate around zero."""
        t = np.linspace(0, 8 * np.pi, 300)
        s = pd.Series(100 + 10 * np.sin(t))
        macd, _, _ = _macd(s)
        assert macd.dropna().min() < 0 and macd.dropna().max() > 0


# ── Bollinger Bands ───────────────────────────────────────────────────────────

class TestBollinger:
    def test_upper_above_mid_above_lower(self, price_series):
        upper, mid, lower = _bollinger(price_series, 20)
        valid = pd.concat([upper, mid, lower], axis=1).dropna()
        assert (valid.iloc[:, 0] > valid.iloc[:, 1]).all()
        assert (valid.iloc[:, 1] > valid.iloc[:, 2]).all()

    def test_mid_equals_sma(self, price_series):
        _, mid, _ = _bollinger(price_series, 20)
        sma = _sma(price_series, 20)
        pd.testing.assert_series_equal(mid.dropna(), sma.dropna(), check_names=False)

    def test_band_width_proportional_to_std(self):
        """Higher std multiplier → wider bands."""
        s = pd.Series([float(i) + (i % 5) for i in range(100)])
        upper1, _, lower1 = _bollinger(s, 20, std=1.0)
        upper2, _, lower2 = _bollinger(s, 20, std=2.0)
        width1 = (upper1 - lower1).dropna().mean()
        width2 = (upper2 - lower2).dropna().mean()
        assert width2 == pytest.approx(width1 * 2, rel=1e-6)


# ── ATR ───────────────────────────────────────────────────────────────────────

class TestATR:
    def test_always_positive(self, ohlcv_df):
        result = _atr(ohlcv_df, 14).dropna()
        assert (result > 0).all()

    def test_length_preserved(self, ohlcv_df):
        assert len(_atr(ohlcv_df, 14)) == len(ohlcv_df)

    def test_high_volatility_gives_larger_atr(self):
        """Doubling the High-Low range should roughly double ATR."""
        n = 100
        rng = np.random.default_rng(0)
        base = pd.DataFrame({
            "High":  100 + rng.uniform(0, 1, n),
            "Low":   100 - rng.uniform(0, 1, n),
            "Close": np.full(n, 100.0),
        })
        wide = base.copy()
        wide["High"] = 100 + rng.uniform(0, 2, n)
        wide["Low"]  = 100 - rng.uniform(0, 2, n)
        atr_base = _atr(base, 14).dropna().mean()
        atr_wide = _atr(wide, 14).dropna().mean()
        assert atr_wide > atr_base


# ── compute_indicators ────────────────────────────────────────────────────────

class TestComputeIndicators:
    EXPECTED_COLS = [
        "Open", "High", "Low", "Close", "Volume",
        "SMA_20", "SMA_50", "EMA_12", "EMA_26",
        "RSI_14", "MACD", "MACD_signal", "MACD_hist",
        "BB_upper", "BB_mid", "BB_lower", "ATR_14",
    ]

    def test_all_columns_present(self, ohlcv_df):
        result = compute_indicators(ohlcv_df)
        for col in self.EXPECTED_COLS:
            assert col in result.columns, f"Missing column: {col}"

    def test_no_nan_after_warmup_dropped(self, ohlcv_df):
        result = compute_indicators(ohlcv_df)
        assert not result.isna().any().any()

    def test_row_count_reduced_by_warmup(self, ohlcv_df):
        result = compute_indicators(ohlcv_df)
        # SMA_50 requires 50 rows, so at most len-49 rows remain
        assert len(result) <= len(ohlcv_df) - 49

    def test_input_not_mutated(self, ohlcv_df):
        original_len = len(ohlcv_df)
        compute_indicators(ohlcv_df)
        assert len(ohlcv_df) == original_len


# ── market_summary ─────────────────────────────────────────────────────────────

class TestMarketSummary:
    def test_returns_string(self, ohlcv_df):
        df = compute_indicators(ohlcv_df)
        assert isinstance(market_summary(df), str)

    def test_contains_key_fields(self, ohlcv_df):
        df = compute_indicators(ohlcv_df)
        s = market_summary(df)
        for keyword in ["Close", "SMA50", "Trend", "RSI", "Volume", "Available indicators"]:
            assert keyword in s, f"market_summary missing: {keyword}"

    def test_trend_label_correct(self, ohlcv_df):
        df = compute_indicators(ohlcv_df)
        last = df.iloc[-1]
        s = market_summary(df)
        expected_trend = "uptrend" if last["Close"] > last["SMA_50"] else "downtrend"
        assert expected_trend in s
