"""
Strategy: MyStrat
Ticker:   NVDA
ID:       1
Parameters:
#   n = 20
#   threshold = 0.5

A test strategy
"""

import numpy as np
import pandas as pd
from backtesting import Strategy
from backtesting.lib import crossover

class TestStrat(Strategy): pass