"""calculator: safe arithmetic via simpleeval (docs/07 §2, TD-9)."""

from __future__ import annotations

import ast
import math
import operator

import simpleeval
from pydantic import BaseModel, Field

from nova.core.errors import ToolError
from nova.tools.base import Tool, ToolContext, ToolOutput, ToolSpec

_MAX_EXPRESSION_LEN = 200
_MAX_EXPONENT = 1000
_MAX_MAGNITUDE = 1e100


class CalculatorParams(BaseModel):
    """Arguments for the calculator tool."""

    expression: str = Field(description="The math expression to evaluate, e.g. '12 * 9'.")


def _bounded_pow(left: float, right: float) -> float:
    if abs(right) > _MAX_EXPONENT:
        raise ToolError(f"Exponent {right} is too large (limit {_MAX_EXPONENT}).", code="too_large")
    return left**right


def _prettify(expression: str) -> str:
    return expression.replace("*", "×").replace("/", "÷").replace("×*", "^")


class CalculatorTool(Tool):
    """Whitelisted operators/functions only — never `eval` (TD-9, A-1)."""

    spec = ToolSpec(
        name="calculator",
        title="Calculator",
        description=(
            "Do math: arithmetic, square roots, rounding. Use whenever the user asks a "
            "math question, e.g. 'what is 12 times 9' or 'square root of 144'."
        ),
        parameters=CalculatorParams,
        sensitive=False,
        icon="calculator",
        detail_template="Working out {expression}",
    )

    def __init__(self) -> None:
        self._eval = simpleeval.SimpleEval(
            operators={
                ast.Add: operator.add,
                ast.Sub: operator.sub,
                ast.Mult: operator.mul,
                ast.Div: operator.truediv,
                ast.FloorDiv: operator.floordiv,
                ast.Mod: operator.mod,
                ast.Pow: _bounded_pow,
                ast.USub: operator.neg,
                ast.UAdd: operator.pos,
            },
            functions={
                "sqrt": math.sqrt,
                "round": round,
                "abs": abs,
                "min": min,
                "max": max,
            },
            names={"pi": math.pi, "e": math.e},
        )

    def execute(self, args: BaseModel, ctx: ToolContext) -> ToolOutput:
        del ctx
        assert isinstance(args, CalculatorParams)
        expression = args.expression.strip()
        if len(expression) > _MAX_EXPRESSION_LEN:
            raise ToolError(
                f"That expression is longer than {_MAX_EXPRESSION_LEN} characters.",
                code="too_large",
            )

        try:
            result = self._eval.eval(expression)
        except ToolError:
            raise
        except (ZeroDivisionError, ValueError, OverflowError) as exc:
            raise ToolError(f"Math error: {exc}", code="math_error") from exc
        except Exception as exc:  # simpleeval raises many small exception types
            raise ToolError(
                f"I couldn't understand the expression {expression!r}: {exc}",
                code="invalid_expression",
            ) from exc

        if not isinstance(result, (int, float)):
            raise ToolError(
                f"The expression {expression!r} didn't produce a number.",
                code="invalid_expression",
            )
        if abs(result) > _MAX_MAGNITUDE:
            raise ToolError("The result is astronomically large.", code="too_large")

        pretty = _prettify(expression)
        shown = int(result) if isinstance(result, float) and result.is_integer() else result
        return ToolOutput(
            data={
                "result": result,
                "expression_pretty": pretty,
                "summary": f"{pretty} = {shown}",
            }
        )
