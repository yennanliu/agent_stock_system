"""
Strategy: PLTRTradingStrategy
Ticker:   PLTR
ID:       4
Parameters:


This `PLTRTradingStrategy` class is designed for backtesting using the `backtesting.py` framework. It makes use of standard trading indicators: the 50-period Simple Moving Average (SMA), the 12-period Exponential Moving Average (EMA), and the 14-period Relative Strength Index (RSI). 

In the `init` method, these indicators are initialized and calculated using the stock's closing prices. The strategy implements a simple logic for trading based on predefined signals:

1. **Buy Signal**: The strate
"""

import numpy as np
import pandas as pd
from backtesting import Strategy
from backtesting.lib import crossover

from backtesting import Strategy

class PLTRTradingStrategy(Strategy):
    # Define the indicators to track
    def init(self):
        self.sma_50 = self.I(SMA, self.data.Close, 50)
        self.ema_12 = self.I(EMA, self.data.Close, 12)
        self.rsi_14 = self.I(RSI, self.data.Close, 14)
        self.atr_14 = self.I(ATR, self.data.High, self.data.Low, self.data.Close, 14)

    # Define the logic for entering a long position
    def buy_signal(self):
        # Bullish if the price is below the 50-SMA and RSI is below 30 (indicating oversold)
        return self.data.Close < self.sma_50 and self.rsi_14 < 30

    # Define the logic for exiting the position
    def sell_signal(self):
        # Bearish if the price goes above the 50-SMA or RSI is above 70 (indicating overbought)
        return self.data.Close > self.sma_50 or self.rsi_14 > 70

    def next(self):
        if self.buy_signal() and not self.position:
            self.buy()
        elif self.sell_signal() and self.position:
            self.sell()