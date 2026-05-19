"""
Strategy: NVDA_Strategy
Ticker:   NVDA
ID:       7
Parameters:


The `NVDA_Strategy` class is a systematic trading strategy built for NVIDIA (ticker: NVDA) using the backtesting.py framework. This strategy is designed to capitalize on the current market conditions represented by the provided market summary.

**Initialization (`init` method):**
- The `init` method initializes the technical indicators used in the strategy. This strategy includes:
  - A 50-period simple moving average (SMA) of the closing prices to determine the overall trend.
  - A 14-period re
"""

import numpy as np
import pandas as pd
from backtesting import Strategy
from backtesting.lib import crossover

import backtesting
from backtesting import Strategy
import pandas as pd

class NVDA_Strategy(Strategy):
    # Define the indicators to be used in the strategy
    def init(self):
        self.sma_50 = self.I(backtesting.lib.SMA, self.data.Close, 50)
        self.rsi = self.I(backtesting.lib.RSI, self.data.Close, 14)
        self.atr = self.I(backtesting.lib.ATR, self.data, 14)

    # Define the strategy logic
    def next(self):
        # Check if price is above SMA50 and RSI is above 50
        if self.data.Close[-1] > self.sma_50[-1] and self.rsi[-1] > 50:
            self.buy(size=1)  # Execute a buy order

        # Implementing a stop loss based on ATR
        if len(self.equity) > 0:  # Check if we are in a position
            stop_loss_level = self.data.Close[-1] - 2 * self.atr[-1]  # Set stop loss at 2 ATR below the entry price
            self.sell(size=1, price=stop_loss_level, sl=stop_loss_level)  # Set the stop loss