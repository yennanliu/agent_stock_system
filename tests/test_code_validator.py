"""Tests for AST-based code validator."""
import pytest
from src.tools.code_validator import (
    syntax_check,
    api_conformance_check,
    safety_check,
    run_all_checks,
)

# ── Helpers ────────────────────────────────────────────────────────────────────

CLEAN_STRATEGY = """
class MyStrategy(Strategy):
    n = 20

    def init(self):
        close = self.data.Close
        self.ma = self.I(lambda x: pd.Series(x).rolling(self.n).mean().values, close)

    def next(self):
        if self.data.Close[-1] > self.ma[-1]:
            self.buy()
        else:
            self.sell()
"""


# ── syntax_check ───────────────────────────────────────────────────────────────

class TestSyntaxCheck:
    def test_valid_code_returns_no_issues(self):
        assert syntax_check(CLEAN_STRATEGY) == []

    def test_syntax_error_detected(self):
        bad = "class Foo:\n  def bar(self\n    pass"
        issues = syntax_check(bad)
        assert len(issues) == 1
        assert "SyntaxError" in issues[0]

    def test_empty_string_valid(self):
        assert syntax_check("") == []

    def test_unclosed_paren(self):
        issues = syntax_check("x = (1 + 2")
        assert len(issues) >= 1


# ── api_conformance_check ─────────────────────────────────────────────────────

class TestApiConformanceCheck:
    def test_clean_strategy_passes(self):
        assert api_conformance_check(CLEAN_STRATEGY) == []

    def test_no_strategy_subclass_flagged(self):
        code = """
class MyStrategy:
    def init(self): pass
    def next(self): self.buy()
"""
        issues = api_conformance_check(code)
        assert any("subclassing" in i or "Strategy" in i for i in issues)

    def test_missing_init_flagged(self):
        code = """
class MyStrategy(Strategy):
    def next(self):
        self.buy()
"""
        issues = api_conformance_check(code)
        assert any("init" in i for i in issues)

    def test_missing_next_flagged(self):
        code = """
class MyStrategy(Strategy):
    def init(self):
        self.ma = self.I(lambda x: x, self.data.Close)
"""
        issues = api_conformance_check(code)
        assert any("next" in i for i in issues)

    def test_missing_self_i_flagged(self):
        code = """
class MyStrategy(Strategy):
    def init(self):
        self.ma = self.data.Close  # no self.I() wrapper

    def next(self):
        self.buy()
"""
        issues = api_conformance_check(code)
        assert any("self.I()" in i for i in issues)

    def test_look_ahead_positive_index_flagged(self):
        code = """
class MyStrategy(Strategy):
    def init(self):
        self.ma = self.I(lambda x: x, self.data.Close)

    def next(self):
        if self.data.Close[1] > self.ma[-1]:
            self.buy()
"""
        issues = api_conformance_check(code)
        assert any("look-ahead" in i.lower() or "positive index" in i.lower() for i in issues)

    def test_no_buy_sell_flagged(self):
        code = """
class MyStrategy(Strategy):
    def init(self):
        self.ma = self.I(lambda x: x, self.data.Close)

    def next(self):
        pass
"""
        issues = api_conformance_check(code)
        assert any("buy" in i or "sell" in i for i in issues)

    def test_self_sma_method_call_flagged(self):
        """LLM bug: calling self.SMA(...) instead of module-level helper."""
        code = """
class MyStrategy(Strategy):
    def init(self):
        self.sma = self.I(self.SMA, self.data.Close, 20)
    def next(self):
        self.buy()
"""
        issues = api_conformance_check(code)
        assert any("SMA" in i and "instance method" in i for i in issues)

    def test_self_rsi_method_call_flagged(self):
        code = """
class MyStrategy(Strategy):
    def init(self):
        self.rsi = self.I(self.RSI, self.data.Close, 14)
    def next(self):
        self.buy()
"""
        issues = api_conformance_check(code)
        assert any("RSI" in i and "instance method" in i for i in issues)

    def test_np_convolve_flagged(self):
        """np.convolve truncates output → must be flagged."""
        code = """
class MyStrategy(Strategy):
    def init(self):
        self.sma = self.I(lambda x: np.convolve(x, np.ones(20)/20, mode='valid'), self.data.Close)
    def next(self):
        if self.data.Close[-1] > self.sma[-1]:
            self.buy()
        else:
            self.sell()
"""
        issues = api_conformance_check(code)
        assert any("convolve" in i for i in issues)
        # Also flags mode='valid'
        assert any("valid" in i.lower() for i in issues)

    def test_np_convolve_with_mode_same_still_flagged(self):
        """Even with mode='same', np.convolve is risky — always flag it."""
        code = """
class MyStrategy(Strategy):
    def init(self):
        self.sma = self.I(lambda x: np.convolve(x, np.ones(20)/20, mode='same'), self.data.Close)
    def next(self):
        self.buy()
"""
        issues = api_conformance_check(code)
        assert any("convolve" in i for i in issues)

    def test_mode_valid_keyword_flagged_anywhere(self):
        """mode='valid' anywhere should be flagged."""
        code = """
class MyStrategy(Strategy):
    def init(self):
        self.x = self.I(lambda x: np.correlate(x, [1,1,1], mode='valid'), self.data.Close)
    def next(self):
        self.buy()
"""
        issues = api_conformance_check(code)
        assert any("valid" in i.lower() for i in issues)

    def test_module_level_sma_not_flagged(self):
        """Using SMA directly (not self.SMA) must NOT be flagged."""
        code = """
class MyStrategy(Strategy):
    def init(self):
        self.sma = self.I(SMA, self.data.Close, 20)
    def next(self):
        if self.data.Close[-1] > self.sma[-1]:
            self.buy()
        else:
            self.sell()
"""
        issues = api_conformance_check(code)
        assert not any("instance method" in i for i in issues)

    def test_negative_index_not_flagged(self):
        """[-1] and [-2] are correct — must NOT be flagged."""
        code = """
class MyStrategy(Strategy):
    def init(self):
        self.ma = self.I(lambda x: x, self.data.Close)

    def next(self):
        if self.data.Close[-1] > self.data.Close[-2]:
            self.buy()
        else:
            self.sell()
"""
        issues = api_conformance_check(code)
        assert not any("look-ahead" in i.lower() for i in issues)


# ── safety_check ──────────────────────────────────────────────────────────────

class TestSafetyCheck:
    def test_clean_code_passes(self):
        assert safety_check(CLEAN_STRATEGY) == []

    def test_import_os_flagged(self):
        code = "import os\n" + CLEAN_STRATEGY
        issues = safety_check(code)
        assert any("os" in i for i in issues)

    def test_import_subprocess_flagged(self):
        code = "import subprocess\n" + CLEAN_STRATEGY
        issues = safety_check(code)
        assert any("subprocess" in i for i in issues)

    def test_import_sys_flagged(self):
        code = "import sys\n" + CLEAN_STRATEGY
        issues = safety_check(code)
        assert any("sys" in i for i in issues)

    def test_open_builtin_flagged(self):
        code = CLEAN_STRATEGY.replace("self.buy()", "open('/etc/passwd'); self.buy()")
        issues = safety_check(code)
        assert any("open" in i for i in issues)

    def test_eval_flagged(self):
        code = CLEAN_STRATEGY.replace("self.buy()", "eval('1+1'); self.buy()")
        issues = safety_check(code)
        assert any("eval" in i for i in issues)

    def test_ta_import_flagged(self):
        code = "import ta\n" + CLEAN_STRATEGY
        issues = safety_check(code)
        assert any("ta" in i.lower() for i in issues)

    def test_talib_import_flagged(self):
        code = "import talib\n" + CLEAN_STRATEGY
        issues = safety_check(code)
        assert any("talib" in i.lower() for i in issues)

    def test_pandas_ta_import_flagged(self):
        code = "import pandas_ta\n" + CLEAN_STRATEGY
        issues = safety_check(code)
        assert any("pandas_ta" in i.lower() for i in issues)

    def test_ta_attribute_access_flagged(self):
        code = CLEAN_STRATEGY.replace(
            "self.buy()",
            "x = ta.trend.sma_indicator(self.data.Close, 20); self.buy()"
        )
        issues = safety_check(code)
        assert any("ta" in i.lower() for i in issues)

    def test_numpy_import_allowed(self):
        """import numpy should NOT be flagged."""
        code = "import numpy as np\n" + CLEAN_STRATEGY
        issues = safety_check(code)
        assert not any("numpy" in i.lower() for i in issues)

    def test_pandas_import_allowed(self):
        """import pandas should NOT be flagged."""
        code = "import pandas as pd\n" + CLEAN_STRATEGY
        issues = safety_check(code)
        assert not any("pandas" in i.lower() and "unavailable" in i.lower() for i in issues)


# ── run_all_checks ────────────────────────────────────────────────────────────

class TestRunAllChecks:
    def test_clean_strategy_zero_issues(self):
        assert run_all_checks(CLEAN_STRATEGY) == []

    def test_multiple_issues_all_returned(self):
        """Code with both a look-ahead and a forbidden import should return both."""
        bad = """
import os
class MyStrategy(Strategy):
    def init(self):
        self.ma = self.I(lambda x: x, self.data.Close)
    def next(self):
        if self.data.Close[1] > 0:
            self.buy()
"""
        issues = run_all_checks(bad)
        has_os = any("os" in i for i in issues)
        has_lookahead = any("look-ahead" in i.lower() or "positive index" in i.lower() for i in issues)
        assert has_os and has_lookahead

    def test_syntax_error_stops_further_checks_gracefully(self):
        """A syntax error should return at least one issue without crashing."""
        issues = run_all_checks("class Broken(Strategy):\n  def init(self\n    pass")
        assert len(issues) >= 1
