import ast
import re


FORBIDDEN_IMPORTS = {"os", "subprocess", "sys", "shutil", "socket", "builtins", "importlib"}
FORBIDDEN_BUILTINS = {"open", "eval", "compile"}
# Note: __import__ is allowed but sandboxed — only numpy/pandas/math permitted at runtime


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

    return issues


def safety_check(src: str) -> list[str]:
    issues = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []

    for node in ast.walk(tree):
        # Forbidden imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FORBIDDEN_IMPORTS:
                    issues.append(f"Forbidden import: '{alias.name}'.")
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in FORBIDDEN_IMPORTS:
                issues.append(f"Forbidden import from: '{node.module}'.")

        # Forbidden builtins
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_BUILTINS:
                issues.append(f"Forbidden builtin call: '{node.func.id}()'.")

    return issues


def run_all_checks(src: str) -> list[str]:
    return syntax_check(src) + api_conformance_check(src) + safety_check(src)
