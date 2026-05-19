"""
Strategy: TSMStrategy
Ticker:   TSM
ID:       5
Parameters:


In this implementation of the TSM trading strategy using the backtesting.py framework, we define a class `TSMStrategy` that inherits from `Strategy`. The `init` method initializes several technical indicators: SMA50, SMA20, EMA12, EMA26, RSI14, and ATR14. These indicators are calculated using historical price data, which will help inform the strategy's buy and sell decisions.

The `next` method contains the core logic for trading decisions. A buy signal is generated when the 14-period RSI (RSI14
"""

import numpy as np
import pandas as pd
from backtesting import Strategy
from backtesting.lib import crossover

from backtesting import Strategy

class TSMStrategy(Strategy):
    def init(self):
        # Initialize indicators
        self.sma50 = self.I(self.SMA, self.data.Close, 50)
        self.sma20 = self.I(self.SMA, self.data.Close, 20)
        self.ema12 = self.I(self.EMA, self.data.Close, 12)
        self.ema26 = self.I(self.EMA, self.data.Close, 26)
        self.rsi14 = self.I(self.RSI, self.data.Close, 14)
        self.atr14 = self.I(self.ATR, self.data.High, self.data.Low, self.data.Close, 14)

    def next(self):
        # Trading logic
        if self.rsi14[-1] < 30 and self.data.Close[-1] < self.sma20[-1]:
            # Buy signal when RSI is oversold and price is below SMA20
            self.buy()
        
        elif self.rsi14[-1] > 70 and self.data.Close[-1] > self.sma20[-1]:
            # Sell signal when RSI is overbought and price is above SMA20
            self.sell()

        # Exit conditions
        if self.position:
            if self.data.Close[-1] < self.sma50[-1] or self.data.Close[-1] < self.ema12[-1]:
                self.position.close()  # Close the position if the price drops below SMA50 or EMA12