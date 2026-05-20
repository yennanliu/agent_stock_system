"""
Strategy: NVDA_Trading_Strategy
Ticker:   NVDA
ID:       2
Parameters:


This `NVDA_Trading_Strategy` class is designed for backtesting a systematic trading strategy specifically for NVIDIA (NVDA). The strategy utilizes common technical indicators to help determine when to buy or sell the stock.

### Indicators Used:
1. **Simple Moving Average (SMA)**: Two SMAs are used, one over a 20-day period (`sma20`) and another over a 50-day period (`sma50`). The strategy will look to buy when the stock price is above both simple moving averages, suggesting a bullish trend.
  

"""

import numpy as np
import pandas as pd
from backtesting import Strategy
from backtesting.lib import crossover

class NVDA_Trading_Strategy(Strategy):
    def init(self):
        # Initialize indicators
        self.sma20 = self.I(SMA, self.data.Close, 20)
        self.sma50 = self.I(SMA, self.data.Close, 50)
        self.atrl = self.I(ATR, self.data.High, self.data.Low, self.data.Close, 14)
        self.rsi = self.I(RSI, self.data.Close, 14)

    def next(self):
        # Define trading signals
        buy_signal = self.data.Close[-1] > self.sma20[-1] and self.data.Close[-1] > self.sma50[-1] and self.rsi[-1] < 70
        sell_signal = self.data.Close[-1] < self.sma20[-1] and self.rsi[-1] > 30
        
        # Execute trades
        if buy_signal:
            self.buy()
        elif sell_signal:
            self.sell()