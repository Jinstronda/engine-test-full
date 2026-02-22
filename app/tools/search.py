"""Tavily web search tool.

Requires: TAVILY_API_KEY environment variable.
Install:  pip install tavily-python
"""

from __future__ import annotations

import logging
import os

from langchain_core.tools import tool

from app.tools import register

logger = logging.getLogger(__name__)


@register
@tool
async def tavily_search(query: str) -> str:
    """Search the web using Tavily and return the top results as formatted text.

    Use this for real-time information, company news, recent events, or any
    question that benefits from live web data.

    Args:
        query: The search query string.

    Returns:
        A formatted string with the top search results (title, URL, snippet).
    """
    try:
        from tavily import AsyncTavilyClient
    except ImportError:
        return "Error: tavily-python is not installed. Run: pip install tavily-python"

    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        return "Error: TAVILY_API_KEY environment variable is not set."

    try:
        client = AsyncTavilyClient(api_key=api_key)
        response = await client.search(
            query=query,
            max_results=5,
            search_depth="basic",
        )
        results = response.get("results", [])
        if not results:
            return f"No results found for: {query}"

        lines = [f"Search results for: {query}\n"]
        for i, r in enumerate(results, 1):
            title = r.get("title", "Untitled")
            url = r.get("url", "")
            content = r.get("content", "").strip()
            snippet = content[:300] + "..." if len(content) > 300 else content
            lines.append(f"{i}. {title}\n   URL: {url}\n   {snippet}\n")

        return "\n".join(lines)

    except Exception as e:
        logger.warning("tavily_search failed for %r: %s", query, e)
        return f"Search failed: {e}"
