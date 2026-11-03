import pytest

from apps.catalog.formula import FormulaError, evaluate


@pytest.mark.parametrize("expr, env, expected", [
    ("H - 2*T", {"H": 720, "T": 18}, 684),
    ("2 if W > 600 else 1", {"W": 800}, 2),
    ("drawers > 0 and front == 'lac'", {"drawers": 3, "front": "lac"}, True),
    ("ceil((W - 4) / 600)", {"W": 1200}, 2),
    ("min(140, (H - 4) / 3 - 43)", {"H": 720}, 140),
    ("min(140, (H - 4) / 4 - 43)", {"H": 400}, 56),
    ("300 <= W <= 1200", {"W": 1300}, False),
    ("not drawers", {"drawers": 0}, True),
])
def test_evaluates(expr, env, expected):
    assert evaluate(expr, env) == expected


@pytest.mark.parametrize("expr", [
    "__import__('os').system('ls')",
    "W.__class__",
    "[x for x in range(3)]",
    "open('x')",
    "lambda: 1",
    "W[0]",
    "2 ** 1000",
])
def test_rejects_unsafe_or_unsupported(expr):
    with pytest.raises(FormulaError):
        evaluate(expr, {"W": 800})


def test_unknown_name_is_reported():
    with pytest.raises(FormulaError, match="Unknown name 'X'"):
        evaluate("X + 1", {})


def test_division_by_zero_is_a_formula_error():
    with pytest.raises(FormulaError, match="Division by zero"):
        evaluate("H / drawers", {"H": 720, "drawers": 0})
