"""
EDITH Tools — Web Search

Search the internet using DuckDuckGo (via the ddgs library).
"""

from __future__ import annotations

import logging

from tools.registry import registry

logger = logging.getLogger("edith.tools.web_search")


@registry.register(
    name="web_search",
    description="Search the internet using DuckDuckGo. Returns titles, URLs, and snippets for the top results. Use this when the user asks to search the web, look something up, or find information online.",
    parameters={
        "query": {
            "type": "string",
            "description": "The search query (e.g., 'latest AI news 2026', 'weather in Delhi')",
        },
        "max_results": {
            "type": "integer",
            "description": "Maximum number of results to return. Defaults to 5.",
        },
    },
    required=["query"],
)
def web_search(query: str, max_results: int = 5) -> str:
    """Search the web using DuckDuckGo."""
    try:
        from ddgs import DDGS

        max_results = max(1, min(max_results, 10))

        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))

        if not results:
            return f"No results found for: '{query}'"

        lines = [f"Web search results for '{query}':\n"]
        for i, r in enumerate(results, 1):
            title = r.get("title", "Untitled")
            url = r.get("href", r.get("link", ""))
            snippet = r.get("body", r.get("snippet", ""))

            lines.append(f"  [{i}] {title}")
            lines.append(f"      URL: {url}")
            if snippet:
                # Truncate long snippets
                if len(snippet) > 200:
                    snippet = snippet[:197] + "…"
                lines.append(f"      {snippet}")
            lines.append("")

        return "\n".join(lines)

    except ImportError:
        return "Error: The 'ddgs' package is not installed. Run: pip install ddgs"
    except Exception as e:
        return f"Error searching the web: {type(e).__name__}: {e}"
