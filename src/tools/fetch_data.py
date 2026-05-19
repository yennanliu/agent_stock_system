import pandas as pd
import yfinance as yf


def fetch_ohlcv(ticker: str, period: str = "2y") -> pd.DataFrame:
    df = yf.download(ticker, period=period, auto_adjust=True, progress=False)
    if df.empty:
        raise ValueError(f"No data returned for ticker '{ticker}'. Check the symbol.")
    # Flatten multi-level columns that yfinance sometimes returns
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.index = pd.to_datetime(df.index)
    df.sort_index(inplace=True)
    return df
