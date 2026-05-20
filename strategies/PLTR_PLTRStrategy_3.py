"""
Strategy: PLTRStrategy
Ticker:   PLTR
ID:       3
Parameters:
#   SMA_PERIOD = 50
#   ATR_PERIOD = 14
#   RSI_PERIOD = 14
#   above_rsi = 55
#   below_rsi = 45

The `PLTRStrategy` class designed for backtesting uses a combination of technical indicators suitable for the current market conditions of PLTR. The strategy initializes with three key indicators: a 50-period Simple Moving Average (SMA), a 14-period Average True Range (ATR), and a 14-period Relative Strength Index (RSI). 

1. **Indicators**:
   - **SMA** helps provide insight into the overall trend of the stock. In this case, the current market trend is a downtrend, which will be crucial for our
"""

import numpy as np
import pandas as pd
from backtesting import Strategy
from backtesting.lib import crossover

import backtesting
from backtesting import Strategy
import pandas as pd

class PLTRStrategy(Strategy):
    # Define the parameters for the strategy
    SMA_PERIOD = 50
    ATR_PERIOD = 14
    RSI_PERIOD = 14
    above_rsi = 55
    below_rsi = 45
    
    def init(self):
        # Initialize indicators
        self.sma = self.I(pd.Series.rolling, self.data.Close, self.SMA_PERIOD).mean()
        self.atr = self.I(pd.Series.rolling, self.data.Close, self.ATR_PERIOD).apply(self.atr_func)
        self.rsi = self.I(lambda x: self.rsi_func(x, self.RSI_PERIOD), self.data.Close)

    def atr_func(self, prices):
        return max(prices[-self.ATR_PERIOD:]) - min(prices[-self.ATR_PERIOD:])

    def rsi_func(self, prices, period):
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))
    
    def next(self):
        # Trading logic
        if self.rsi[-1] < self.below_rsi and self.data.Close[-1] < self.sma[-1]:
            self.buy()
        elif self.rsi[-1] > self.above_rsi and self.data.Close[-1] > self.sma[-1]:
            self.sell()

# Sample for how to run the strategy
# from backtesting import Backtest
# bt = Backtest(data, PLTRStrategy, cash=10_000, commission=.002)
# stats = bt.run()
# bt.plot()