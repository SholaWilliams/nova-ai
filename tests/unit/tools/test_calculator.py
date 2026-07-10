"""calculator: happy path + every declared error code (docs/07 §2)."""

from __future__ import annotations

import pytest

from nova.core.errors import ToolError
from nova.tools.base import ToolContext
from nova.tools.calculator import CalculatorParams, CalculatorTool


def _run(expression: str, ctx: ToolContext) -> dict:
    return CalculatorTool().execute(CalculatorParams(expression=expression), ctx).data


def test_basic_arithmetic(ctx: ToolContext) -> None:
    data = _run("12 * 9", ctx)
    assert data["result"] == 108
    assert data["summary"] == "12 × 9 = 108"


def test_functions_and_constants(ctx: ToolContext) -> None:
    assert _run("sqrt(144)", ctx)["result"] == 12
    assert _run("round(pi, 2)", ctx)["result"] == 3.14
    assert _run("max(1, 2, 3)", ctx)["result"] == 3


def test_division_by_zero_is_math_error(ctx: ToolContext) -> None:
    with pytest.raises(ToolError) as excinfo:
        _run("1 / 0", ctx)
    assert excinfo.value.code == "math_error"


def test_unparseable_expression(ctx: ToolContext) -> None:
    with pytest.raises(ToolError) as excinfo:
        _run("hello world", ctx)
    assert excinfo.value.code == "invalid_expression"


def test_huge_exponent_rejected(ctx: ToolContext) -> None:
    with pytest.raises(ToolError) as excinfo:
        _run("2 ** 5000", ctx)
    assert excinfo.value.code == "too_large"


def test_huge_result_rejected(ctx: ToolContext) -> None:
    with pytest.raises(ToolError) as excinfo:
        _run("9e99 * 100", ctx)
    assert excinfo.value.code == "too_large"


def test_expression_length_cap(ctx: ToolContext) -> None:
    with pytest.raises(ToolError) as excinfo:
        _run("1+" * 150 + "1", ctx)
    assert excinfo.value.code == "too_large"


def test_no_python_escape_hatch(ctx: ToolContext) -> None:
    """A-1: names/functions outside the whitelist never evaluate."""
    with pytest.raises(ToolError) as excinfo:
        _run("__import__('os')", ctx)
    assert excinfo.value.code == "invalid_expression"
