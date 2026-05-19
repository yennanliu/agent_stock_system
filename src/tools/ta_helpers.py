"""
Technical indicator functions designed to be called from inside
backtesting.py Strategy classes via `self.I(FUNC, data, ...)`.

Each function takes raw numpy/pandas arrays and returns a numpy array
of the same length. They are exposed in the strategy execution scope
so the LLM can write `self.I(SMA, close, 20)` directly.
"""
import numpy as np
import pandas as pd


def SMA(values, n: int) -> np.ndarray:
    """Simple Moving Average."""
    return pd.Series(values).rolling(n).mean().values


def EMA(values, n: int) -> np.ndarray:
    """Exponential Moving Average."""
    return pd.Series(values).ewm(span=n, adjust=False).mean().values


def RSI(values, n: int = 14) -> np.ndarray:
    """Relative Strength Index (0–100)."""
    s = pd.Series(values)
    delta = s.diff()
    gain = delta.clip(lower=0).rolling(n).mean()
    loss = (-delta.clip(upper=0)).rolling(n).mean()
    rs = gain / loss.where(loss != 0, other=np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.where(loss != 0, other=100.0)
    return rsi.values


def MACD(values, fast: int = 12, slow: int = 26) -> np.ndarray:
    """MACD line = EMA(fast) − EMA(slow)."""
    s = pd.Series(values)
    return (
        s.ewm(span=fast, adjust=False).mean() - s.ewm(span=slow, adjust=False).mean()
    ).values


def MACD_SIGNAL(values, fast: int = 12, slow: int = 26, signal: int = 9) -> np.ndarray:
    """Signal line of MACD = EMA of MACD line."""
    s = pd.Series(values)
    macd = s.ewm(span=fast, adjust=False).mean() - s.ewm(span=slow, adjust=False).mean()
    return macd.ewm(span=signal, adjust=False).mean().values


def BBANDS_UPPER(values, n: int = 20, k: float = 2.0) -> np.ndarray:
    """Bollinger upper band = SMA(n) + k × stdev(n)."""
    s = pd.Series(values)
    return (s.rolling(n).mean() + k * s.rolling(n).std()).values


def BBANDS_MID(values, n: int = 20) -> np.ndarray:
    """Bollinger middle band = SMA(n)."""
    return pd.Series(values).rolling(n).mean().values


def BBANDS_LOWER(values, n: int = 20, k: float = 2.0) -> np.ndarray:
    """Bollinger lower band = SMA(n) − k × stdev(n)."""
    s = pd.Series(values)
    return (s.rolling(n).mean() - k * s.rolling(n).std()).values


def ATR(high, low, close, n: int = 14) -> np.ndarray:
    """Average True Range over n periods."""
    h, l, c = pd.Series(high), pd.Series(low), pd.Series(close)
    tr = pd.concat(
        [h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1
    ).max(axis=1)
    return tr.rolling(n).mean().values


def STDEV(values, n: int = 20) -> np.ndarray:
    """Rolling standard deviation."""
    return pd.Series(values).rolling(n).std().values


def HIGHEST(values, n: int) -> np.ndarray:
    """Rolling maximum over n periods."""
    return pd.Series(values).rolling(n).max().values


def LOWEST(values, n: int) -> np.ndarray:
    """Rolling minimum over n periods."""
    return pd.Series(values).rolling(n).min().values


# Public registry — added to the strategy execution scope
TA_HELPERS = {
    "SMA": SMA,
    "EMA": EMA,
    "RSI": RSI,
    "MACD": MACD,
    "MACD_SIGNAL": MACD_SIGNAL,
    "BBANDS_UPPER": BBANDS_UPPER,
    "BBANDS_MID": BBANDS_MID,
    "BBANDS_LOWER": BBANDS_LOWER,
    "ATR": ATR,
    "STDEV": STDEV,
    "HIGHEST": HIGHEST,
    "LOWEST": LOWEST,
}
