import ast
import re


FORBIDDEN_IMPORTS = {"os", "subprocess", "sys", "shutil", "socket", "builtins", "importlib"}
FORBIDDEN_BUILTINS = {"open", "eval", "compile"}
# Note: __import__ is allowed but sandboxed — only numpy/pandas/math permitted at runtime

# TA libraries not installed in the runtime sandbox
UNAVAILABLE_TA_LIBS = {"ta", "talib", "pandas_ta", "finta", "stockstats", "ta_lib"}

# Functions that exist in backtesting.lib (the only valid ones to use from that module)
_VALID_BACKTESTING_LIB = {"crossover", "cross", "barssince", "resample_apply"}


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

    # Bare OHLCV names used in self.I() without prior assignment in init()
    # e.g. self.I(SMA, close, 20) where `close` was never assigned.
    # Walk each method body to collect assigned names, then check self.I() args.
    _OHLCV_BARE = {"close", "high", "low", "open", "volume",
                   "Close", "High", "Low", "Open", "Volume"}
    for method in ast.walk(cls):
        if not isinstance(method, ast.FunctionDef):
            continue
        assigned: set[str] = set()
        for stmt in ast.walk(method):
            if isinstance(stmt, ast.Assign):
                for t in stmt.targets:
                    if isinstance(t, ast.Name):
                        assigned.add(t.id)
            # Check every self.I() call in this method
            if (
                isinstance(stmt, ast.Call)
                and isinstance(stmt.func, ast.Attribute)
                and isinstance(stmt.func.value, ast.Name)
                and stmt.func.value.id == "self"
                and stmt.func.attr == "I"
                and len(stmt.args) >= 2
            ):
                data_arg = stmt.args[1]
                if isinstance(data_arg, ast.Name) and data_arg.id in _OHLCV_BARE:
                    if data_arg.id not in assigned:
                        issues.append(
                            f"Bare name '{data_arg.id}' used in self.I() but never assigned in this method. "
                            f"Use self.data.Close (or .High/.Low) directly: "
                            f"self.I(FUNC, self.data.Close, n)."
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
                f"Use the module-level helper directly: self.I({node.attr}, self.data.Close, n)."
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
                "self.I(SMA, self.data.Close, n)."
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


def import_check(src: str) -> list[str]:
    """Any import statement in strategy code is unnecessary and likely harmful."""
    issues = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = ", ".join(a.name for a in node.names)
            issues.append(
                f"Remove 'import {names}' — all required names (Strategy, np, pd, "
                "crossover, SMA, EMA, RSI, ATR, …) are already in scope. "
                "Do NOT add any import statements."
            )
        if isinstance(node, ast.ImportFrom):
            issues.append(
                f"Remove 'from {node.module} import ...' — all required names are "
                "already in scope. Do NOT add any import statements."
            )
    return issues


def safety_check(src: str) -> list[str]:
    issues = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []

    # Build a map of local name → canonical module name for all imports.
    # e.g. `import backtesting as bt`  → {"bt": "backtesting"}
    #      `import backtesting`         → {"backtesting": "backtesting"}
    import_aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname if alias.asname else alias.name.split(".")[0]
                import_aliases[local] = alias.name.split(".")[0]
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                local = alias.asname if alias.asname else alias.name
                import_aliases[local] = node.module.split(".")[0]

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
                # from backtesting import indicators
                if node.module == "backtesting" and any(
                    alias.name == "indicators" for alias in (node.names or [])
                ):
                    issues.append(
                        "backtesting.indicators does not exist. "
                        "Use module-level TA helpers (SMA, EMA, RSI, ATR, …) with self.I()."
                    )

        # Attribute access on unavailable TA libs (e.g. ta.trend.sma_indicator)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            canonical = import_aliases.get(node.value.id, node.value.id)
            if canonical in UNAVAILABLE_TA_LIBS:
                issues.append(
                    f"Unavailable TA library call: '{node.value.id}.{node.attr}'. "
                    "Rewrite using pd.Series and np operations only."
                )

            # <backtesting_alias>.indicators — e.g. bt.indicators or backtesting.indicators
            if canonical == "backtesting" and node.attr == "indicators":
                issues.append(
                    f"backtesting.indicators does not exist (used as '{node.value.id}.indicators'). "
                    "Use module-level TA helpers (SMA, EMA, RSI, ATR, …) with self.I()."
                )

        # <backtesting_alias>.indicators.FUNC — e.g. bt.indicators.SMA(...)
        # also <backtesting_alias>.lib.FUNC where FUNC is not a real lib function
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute):
            parent_name = node.value.value.id if isinstance(node.value.value, ast.Name) else None
            if parent_name and import_aliases.get(parent_name, parent_name) == "backtesting":
                if node.value.attr == "indicators":
                    issues.append(
                        f"backtesting.indicators does not exist ('{parent_name}.indicators.{node.attr}'). "
                        f"Use the module-level TA helper instead: self.I({node.attr}, self.data.Close, n)."
                    )
                elif node.value.attr == "lib" and node.attr not in _VALID_BACKTESTING_LIB:
                    issues.append(
                        f"backtesting.lib.{node.attr} does not exist. "
                        f"backtesting.lib only provides: {', '.join(sorted(_VALID_BACKTESTING_LIB))}. "
                        f"Use the module-level TA helper instead: self.I({node.attr}, self.data.Close, n)."
                    )

        # Forbidden builtins
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_BUILTINS:
                issues.append(f"Forbidden builtin call: '{node.func.id}()'.")

    return issues


def position_sizing_check(src: str) -> list[str]:
    """Detect buy(size=N) where N > 0.95 (leverage) or bare buy() inside an already-open position."""
    issues = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []

    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "buy"
        ):
            continue
        for kw in node.keywords:
            if kw.arg == "size" and isinstance(kw.value, ast.Constant):
                val = kw.value.value
                if isinstance(val, (int, float)) and val > 0.95:
                    issues.append(
                        f"self.buy(size={val}) exceeds safe position limit. "
                        "Use size ≤ 0.95 to avoid margin exhaustion. "
                        "Omitting size (100% of cash) is also acceptable."
                    )
    return issues


def run_all_checks(src: str) -> list[str]:
    return (
        syntax_check(src)
        + import_check(src)
        + api_conformance_check(src)
        + safety_check(src)
        + position_sizing_check(src)
    )
