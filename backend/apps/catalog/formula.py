"""A small, safe expression language for BOM and routing formulas.

Examples used in templates:
    H - 2*T                       panel length from cabinet height and board thickness
    2 if W <= 600 else 3          hinge count
    drawers > 0 and front == 'lac'
    ceil((W - 4) / 600)           number of doors

Only arithmetic, comparisons, boolean logic, conditional expressions, string and
number literals, parameter names and a few whitelisted functions are allowed.
Anything else (attribute access, calls to other functions, comprehensions,
lambdas, subscripts) raises FormulaError, so users can safely edit formulas.
"""
import ast
import math
import operator
from decimal import Decimal


class FormulaError(ValueError):
    pass


_BIN = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg, ast.Not: operator.not_}
_CMP = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}
FUNCTIONS = {
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
    "ceil": math.ceil,
    "floor": math.floor,
}
MAX_LENGTH = 500


def _num(v):
    return float(v) if isinstance(v, Decimal) else v


def evaluate(expr, variables):
    """Evaluate ``expr`` with ``variables``; returns a number, bool or string."""
    if expr is None or str(expr).strip() == "":
        raise FormulaError("Formula is empty")
    expr = str(expr)
    if len(expr) > MAX_LENGTH:
        raise FormulaError("Formula is too long")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise FormulaError(f"Syntax error in '{expr}': {e.msg}") from None
    variables = {k: _num(v) for k, v in variables.items()}
    return _eval(tree.body, variables, expr)


def _eval(node, env, src):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, str, bool)):
            return node.value
        raise FormulaError(f"Unsupported literal in '{src}'")
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        if node.id in ("True", "False"):
            return node.id == "True"
        raise FormulaError(f"Unknown name '{node.id}' in '{src}'")
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        left, right = _eval(node.left, env, src), _eval(node.right, env, src)
        if isinstance(node.op, ast.Pow) and abs(right) > 10:
            raise FormulaError("Exponent too large")
        try:
            return _BIN[type(node.op)](left, right)
        except ZeroDivisionError:
            raise FormulaError(f"Division by zero in '{src}'") from None
        except TypeError:
            raise FormulaError(f"Type error in '{src}'") from None
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand, env, src))
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            result = True
            for v in node.values:
                result = _eval(v, env, src)
                if not result:
                    return result
            return result
        result = False
        for v in node.values:
            result = _eval(v, env, src)
            if result:
                return result
        return result
    if isinstance(node, ast.Compare):
        left = _eval(node.left, env, src)
        for op, comp in zip(node.ops, node.comparators):
            if type(op) not in _CMP:
                raise FormulaError(f"Unsupported comparison in '{src}'")
            right = _eval(comp, env, src)
            if not _CMP[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.IfExp):
        return _eval(node.body if _eval(node.test, env, src) else node.orelse, env, src)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
        fn = FUNCTIONS.get(node.func.id)
        if fn is None:
            raise FormulaError(f"Function '{node.func.id}' is not allowed in '{src}'")
        return fn(*[_eval(a, env, src) for a in node.args])
    raise FormulaError(f"Unsupported expression in '{src}'")


def names_in(expr):
    """Parameter names a formula refers to (for validation in the admin)."""
    try:
        tree = ast.parse(str(expr), mode="eval")
    except SyntaxError:
        return set()
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id not in FUNCTIONS}
