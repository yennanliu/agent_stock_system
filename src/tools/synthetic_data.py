"""
Synthetic OHLCV data generator for the Strategy Playground.

Produces a realistic-looking price series without needing any external API.
Supports configurable trend, volatility, and market regime.
"""
import numpy as np
import pandas as pd


def generate_synthetic_ohlcv(
    n: int = 504,                   # ~2 trading years
    start_price: float = 100.0,
    trend: str = "up",             # up | down | sideways | volatile
    volatility: str = "medium",    # low | medium | high
    seed: int = 42,
) -> pd.DataFrame:
    """
    Return a DataFrame with columns Open/High/Low/Close/Volume and a
    business-day DatetimeIndex starting 2022-01-03.

    Regime presets
    --------------
    up        – steady bull with small pullbacks
    down      – bear market, larger drawdowns
    sideways  – mean-reverting, no clear direction
    volatile  – high-vol mixed-direction (stress test)
    """
    rng = np.random.default_rng(seed)

    # ── Daily returns ─────────────────────────────────────────────────────────
    vol_map   = {"low": 0.008, "medium": 0.015, "high": 0.028}
    drift_map = {
        "up":       +0.0004,
        "down":     -0.0004,
        "sideways":  0.0000,
        "volatile":  0.0001,
    }
    daily_vol   = vol_map.get(volatility, 0.015)
    daily_drift = drift_map.get(trend, 0.0)

    # Geometric Brownian Motion with occasional regime shocks
    noise   = rng.normal(0, daily_vol, n)
    shocks  = rng.choice([0.0, -0.04, +0.04, -0.08, +0.06],
                         p=[0.97, 0.01, 0.01, 0.005, 0.005], size=n)
    # Volatile mode: more frequent large moves
    if trend == "volatile":
        extra = rng.choice([0.0, -0.03, +0.03], p=[0.90, 0.05, 0.05], size=n)
        shocks += extra

    returns = daily_drift + noise + shocks
    log_prices = np.log(start_price) + np.cumsum(returns)
    closes = np.exp(log_prices)

    # ── OHLC from close ───────────────────────────────────────────────────────
    spread = closes * daily_vol * rng.uniform(0.5, 1.5, n)
    highs  = closes + spread * rng.uniform(0.3, 1.0, n)
    lows   = closes - spread * rng.uniform(0.3, 1.0, n)
    opens  = np.roll(closes, 1)  # previous close = today's open
    opens[0] = start_price
    # Intraday gap noise on open
    opens  = opens * np.exp(rng.normal(0, daily_vol * 0.3, n))
    # Clip so open is always within [low, high]
    opens  = np.clip(opens, lows, highs)

    # ── Volume ────────────────────────────────────────────────────────────────
    base_vol = 5_000_000
    volumes  = (base_vol * rng.lognormal(0, 0.5, n)).astype(int)
    # Higher volume on shock days
    volumes  = np.where(np.abs(shocks) > 0.01, volumes * 2, volumes)

    idx = pd.date_range("2022-01-03", periods=n, freq="B")
    df = pd.DataFrame(
        {
            "Open":   np.round(opens,  4),
            "High":   np.round(highs,  4),
            "Low":    np.round(lows,   4),
            "Close":  np.round(closes, 4),
            "Volume": volumes,
        },
        index=idx,
    )
    # Ensure OHLC integrity
    df["High"]  = df[["Open", "High", "Close"]].max(axis=1)
    df["Low"]   = df[["Open", "Low",  "Close"]].min(axis=1)
    return df


PRESET_LABELS = {
    "up":       "Bull Market (steady uptrend)",
    "down":     "Bear Market (downtrend)",
    "sideways": "Sideways / Ranging",
    "volatile": "High-Volatility / Stress",
}
