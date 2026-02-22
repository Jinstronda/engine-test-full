"""Tool registry — global name-based lookup for LangChain tools.

Tools are Python functions decorated with ``@register`` and ``@tool``.
Agents reference them by string name in ``config.yaml`` and the node
factories resolve names to ``BaseTool`` objects at graph-build time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

_registry: dict[str, BaseTool] = {}


def register(tool: BaseTool) -> BaseTool:
    """Add a BaseTool to the registry by its ``.name``.

    Can be used as a decorator (applied *outside* ``@tool``)::

        @register
        @tool
        def my_tool(query: str) -> str:
            ...
    """
    _registry[tool.name] = tool
    return tool


def resolve_tools(names: list[str]) -> list[BaseTool]:
    """Look up tool names and return the corresponding ``BaseTool`` objects.

    Raises ``ValueError`` if any name is not registered.
    """
    missing = [n for n in names if n not in _registry]
    if missing:
        raise ValueError(
            f"Unknown tool(s): {missing}. Available: {list(_registry.keys())}"
        )
    return [_registry[n] for n in names]


def list_tools() -> list[str]:
    """Return all registered tool names."""
    return list(_registry.keys())


# Auto-import builtins so the registry is populated on first access.
import app.tools.builtins as _builtins  # noqa: E402, F401
import app.tools.search as _search  # noqa: E402, F401
import app.tools.ashby as _ashby  # noqa: E402, F401
import app.tools.linkedin as _linkedin  # noqa: E402, F401
import app.tools.document_parser as _document_parser  # noqa: E402, F401
import app.tools.scoring as _scoring  # noqa: E402, F401
import app.tools.email as _email  # noqa: E402, F401
import app.tools.telegram as _telegram  # noqa: E402, F401
import app.tools.stripe as _stripe  # noqa: E402, F401
