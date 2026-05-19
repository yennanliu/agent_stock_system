import pandas as pd
import numpy as np


# ── Indicator calculations (pure pandas/numpy, no external TA lib) ────────────

def _sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = _ema(series, fast)
    ema_slow = _ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _bollinger(series: pd.Series, period: int = 20, std: float = 2.0):
    mid = _sma(series, period)
    sigma = series.rolling(period).std()
    return mid + std * sigma, mid, mid - std * sigma


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.rolling(period).mean()


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    close = df["Close"]

    df["SMA_20"] = _sma(close, 20)
    df["SMA_50"] = _sma(close, 50)
    df["EMA_12"] = _ema(close, 12)
    df["EMA_26"] = _ema(close, 26)
    df["RSI_14"] = _rsi(close, 14)

    macd, macd_sig, macd_hist = _macd(close)
    df["MACD"] = macd
    df["MACD_signal"] = macd_sig
    df["MACD_hist"] = macd_hist

    bb_upper, bb_mid, bb_lower = _bollinger(close)
    df["BB_upper"] = bb_upper
    df["BB_mid"] = bb_mid
    df["BB_lower"] = bb_lower

    df["ATR_14"] = _atr(df, 14)

    # Drop warm-up NaN rows (longest window = SMA_50)
    df.dropna(subset=["SMA_50"], inplace=True)
    return df


def market_summary(df: pd.DataFrame) -> str:
    last = df.iloc[-1]
    close = last["Close"]
    sma50 = last["SMA_50"]
    rsi = last["RSI_14"]
    atr = last["ATR_14"]
    avg_vol = df["Volume"].tail(20).mean()
    last_vol = last["Volume"]

    trend = "uptrend" if close > sma50 else "downtrend"
    vol_pct = (atr / close) * 100
    vol_regime = "high" if vol_pct > 3 else "moderate" if vol_pct > 1.5 else "low"
    rsi_label = "overbought" if rsi > 70 else "oversold" if rsi < 30 else "neutral"
    vol_vs_avg = "above" if last_vol > avg_vol else "below"

    return (
        f"Ticker: {df.index[-1].date()} | Period: {df.index[0].date()} to {df.index[-1].date()}\n"
        f"Close: {close:.2f} | SMA50: {sma50:.2f} | Trend: {trend}\n"
        f"ATR14: {atr:.2f} ({vol_pct:.1f}% of price) | Volatility regime: {vol_regime}\n"
        f"RSI14: {rsi:.1f} ({rsi_label})\n"
        f"Volume: {last_vol:,.0f} ({vol_vs_avg} 20d avg of {avg_vol:,.0f})\n"
        f"Available indicators: SMA_20, SMA_50, EMA_12, EMA_26, RSI_14, "
        f"MACD, MACD_signal, MACD_hist, BB_upper, BB_mid, BB_lower, ATR_14"
    )
