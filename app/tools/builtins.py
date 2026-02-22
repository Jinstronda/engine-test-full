"""Built-in starter tools for the engine.

Add new tools by defining more ``@register`` / ``@tool`` functions here
(or in additional modules under ``app/tools/``).
"""

from __future__ import annotations

from langchain_core.tools import tool

from app.tools import register


@register
@tool
def calculate(expression: str) -> str:
    """Evaluate a mathematical expression and return the result."""
    # Only allow safe math builtins.
    allowed_names = {"abs": abs, "round": round, "min": min, "max": max, "pow": pow}
    try:
        result = eval(expression, {"__builtins__": {}}, allowed_names)  # noqa: S307
        return str(result)
    except Exception as exc:
        return f"Error evaluating '{expression}': {exc}"


@register
@tool
def accept_output(message: str = "") -> str:
    """Signal that the pipeline output is valid. Call this to accept and forward the output."""
    return "__ACCEPTED__"


@register
@tool
def reject_output(reason: str) -> str:
    """Signal that the pipeline output is invalid. Call this to reject and restart the pipeline."""
    return f"__REJECTED__: {reason}"
