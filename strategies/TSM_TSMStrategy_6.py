"""
Strategy: TSMStrategy
Ticker:   TSM
ID:       6
Parameters:
#   sma_short = 20
#   sma_long = 50
#   ema_short = 12
#   ema_long = 26

The `TSMStrategy` class is designed based on the provided market summary for TSM. It leverages several indicators—short-term and long-term simple moving averages (SMA) and exponential moving averages (EMA)—to formulate a trading strategy.

### Key Components:
- **Indicators**: It calculates a short-term SMA (20 days) and a long-term SMA (50 days). Exponential moving averages are also initialized but not visually employed in the provided logic. They can be integrated for further refinements.
  
-
"""

import numpy as np
import pandas as pd
from backtesting import Strategy
from backtesting.lib import crossover

from backtesting import Backtest, Strategy
from backtesting.lib import crossover
import numpy as np

class TSMStrategy(Strategy):
    # Define parameters for the indicators
    sma_short = 20
    sma_long = 50
    ema_short = 12
    ema_long = 26

    def init(self):
        # Initialize indicators
        self.sma_short = self.I(np.convolve, self.data.Close, np.ones(self.sma_short)/self.sma_short, mode='valid')
        self.sma_long = self.I(np.convolve, self.data.Close, np.ones(self.sma_long)/self.sma_long, mode='valid')
        self.ema_short = self.I(np.exp, self.data.Close, self.ema_short)
        self.ema_long = self.I(np.exp, self.data.Close, self.ema_long)

    def next(self):
        # Implementing the strategy logic
        if crossover(self.sma_short, self.sma_long) and self.data.Volume[-1] < 14347415:
            self.buy()  # Buy condition
        elif crossover(self.sma_long, self.sma_short):
            self.sell()  # Sell condition