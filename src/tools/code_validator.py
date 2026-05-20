import ast
import re


FORBIDDEN_IMPORTS = {"os", "subprocess", "sys", "shutil", "socket", "builtins", "importlib"}
FORBIDDEN_BUILTINS = {"open", "eval", "compile"}
# Note: __import__ is allowed but sandboxed — only numpy/pandas/math permitted at runtime

# TA libraries not installed in the runtime sandbox
UNAVAILABLE_TA_LIBS = {"ta", "talib", "pandas_ta", "finta", "stockstats", "ta_lib"}


def syntax_check(src: str) -> list[str]:
    try:
        ast.parse(src)
        return []
    except SyntaxError as e:
        return [f"SyntaxError at line {e.lineno}: {e.msg}"]


def api_conformance_check(src: str) -> list[str]:
    issues = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return ["Cannot check API conformance — syntax errors present."]

    strategy_classes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            bases = [
                (b.id if isinstance(b, ast.Name) else getattr(b, "attr", ""))
                for b in node.bases
            ]
            if "Strategy" in bases:
                strategy_classes.append(node)

    if not strategy_classes:
        issues.append("No class subclassing 'Strategy' found.")
        return issues

    cls = strategy_classes[0]
    method_names = {n.name for n in ast.walk(cls) if isinstance(n, ast.FunctionDef)}

    if "init" not in method_names:
        issues.append("Strategy class is missing an 'init' method.")
    if "next" not in method_names:
        issues.append("Strategy class is missing a 'next' method.")

    # Check self.I() is used for indicators
    has_self_i = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "self"
        and node.func.attr == "I"
        for node in ast.walk(cls)
    )
    if "init" in method_names and not has_self_i:
        issues.append("Indicators must be registered with self.I() in init().")

    # Check for look-ahead: self.data.X[positive_int]
    for node in ast.walk(cls):
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, int)
            and node.slice.value > 0
        ):
            issues.append(
                f"Possible look-ahead detected: positive index [{node.slice.value}] on self.data. "
                "Use negative indices (e.g., [-1], [-2])."
            )

    # buy() or sell() present
    has_order = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in ("buy", "sell", "position")
        for node in ast.walk(cls)
    )
    if not has_order:
        issues.append("No buy() or sell() calls found in the strategy.")

    # self.TA_HELPER(...) called as instance method (e.g. self.SMA(close, 20))
    # — these are module-level functions, not strategy methods.
    TA_NAMES = {"SMA", "EMA", "RSI", "MACD", "MACD_SIGNAL",
                "BBANDS_UPPER", "BBANDS_MID", "BBANDS_LOWER",
                "ATR", "STDEV", "HIGHEST", "LOWEST"}
    for node in ast.walk(cls):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
            and node.attr in TA_NAMES
        ):
            issues.append(
                f"TA helper '{node.attr}' called as instance method (self.{node.attr}). "
                f"Use the module-level helper directly: self.I({node.attr}, close, n)."
            )

    # np.convolve() truncates output unless mode='same' is used — and even then
    # the LLM tends to use mode='valid'. Either way, the right answer is to call
    # the named SMA() helper which preserves length via rolling().mean().
    for node in ast.walk(cls):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "np"
            and node.func.attr == "convolve"
        ):
            issues.append(
                "np.convolve() returns a shorter array than the input and breaks "
                "self.I() length contract. Use the SMA(values, n) helper instead: "
                "self.I(SMA, close, n)."
            )

    # mode='valid' anywhere truncates arrays — usually paired with convolve/correlate
    for node in ast.walk(cls):
        if (
            isinstance(node, ast.keyword)
            and node.arg == "mode"
            and isinstance(node.value, ast.Constant)
            and node.value.value == "valid"
        ):
            issues.append(
                "mode='valid' truncates the output array and breaks indicator length. "
                "Use the named TA helpers (SMA, EMA, RSI, …) which preserve length."
            )

    return issues


def safety_check(src: str) -> list[str]:
    issues = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []

    for node in ast.walk(tree):
        # Forbidden / unavailable imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in FORBIDDEN_IMPORTS:
                    issues.append(f"Forbidden import: '{alias.name}'.")
                elif root in UNAVAILABLE_TA_LIBS:
                    issues.append(
                        f"Unavailable TA library: '{alias.name}'. "
                        "Rewrite using pd.Series and np operations only."
                    )
        if isinstance(node, ast.ImportFrom):
            if node.module:
                root = node.module.split(".")[0]
                if root in FORBIDDEN_IMPORTS:
                    issues.append(f"Forbidden import from: '{node.module}'.")
                elif root in UNAVAILABLE_TA_LIBS:
                    issues.append(
                        f"Unavailable TA library: '{node.module}'. "
                        "Rewrite using pd.Series and np operations only."
                    )

        # Attribute access on unavailable TA libs (e.g. ta.trend.sma_indicator)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id in UNAVAILABLE_TA_LIBS:
                issues.append(
                    f"Unavailable TA library call: '{node.value.id}.{node.attr}'. "
                    "Rewrite using pd.Series and np operations only."
                )

        # backtesting.indicators does not exist — catch both attribute access
        # (backtesting.indicators.SMA) and import (from backtesting import indicators)
        if isinstance(node, ast.Attribute):
            # Walk chain: backtesting.indicators.SMA → value is backtesting.indicators
            if (
                isinstance(node.value, ast.Attribute)
                and node.value.attr == "indicators"
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "backtesting"
            ):
                issues.append(
                    f"backtesting.indicators does not exist. "
                    f"Use the module-level TA helper instead: "
                    f"self.I({node.attr}, self.data.Close, n)."
                )
            elif node.attr == "indicators" and isinstance(node.value, ast.Name) and node.value.id == "backtesting":
                issues.append(
                    "backtesting.indicators does not exist. "
                    "Use module-level TA helpers (SMA, EMA, RSI, ATR, …) with self.I()."
                )
        if isinstance(node, ast.ImportFrom):
            if node.module == "backtesting" and any(
                alias.name == "indicators" for alias in (node.names or [])
            ):
                issues.append(
                    "backtesting.indicators does not exist. "
                    "Use module-level TA helpers (SMA, EMA, RSI, ATR, …) with self.I()."
                )

        # Forbidden builtins
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_BUILTINS:
                issues.append(f"Forbidden builtin call: '{node.func.id}()'.")

    return issues


def run_all_checks(src: str) -> list[str]:
    return syntax_check(src) + api_conformance_check(src) + safety_check(src)
