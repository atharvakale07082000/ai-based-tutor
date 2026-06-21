"""
Web search tool implementation using DuckDuckGo (ddgs).

Used by CurriculumSubAgent to research custom topics that fall outside
the static curriculum.yaml topic graph (e.g. "LangChain deep agents",
"Rust for systems programming", etc.).
"""

from __future__ import annotations

import asyncio

import structlog

from app.tools.schemas import Tool

log = structlog.get_logger()


async def _web_search(query: str, max_results: int = 6) -> dict:
    """Search the web via DuckDuckGo and return snippet results."""
    from ddgs import DDGS

    def _sync_search() -> list[dict]:
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))

    try:
        results = await asyncio.to_thread(_sync_search)
        snippets = [
            {"title": r.get("title", ""), "snippet": r.get("body", ""), "url": r.get("href", "")}
            for r in results
            if r.get("body")
        ]
        log.info("web_search_done", query=query[:80], hits=len(snippets))
        return {"results": snippets, "query": query}
    except Exception as e:
        log.warning("web_search_error", query=query[:80], error=str(e)[:200])
        return {"results": [], "query": query, "error": str(e)[:200]}


TOOLS: list[Tool] = [
    Tool(
        name="web_search",
        description=(
            "Search the web for up-to-date information on any topic. "
            "Use this when the learner asks about a specific technology, framework, or subject "
            "that may not be covered by the static topic graph (e.g. 'LangChain agents', "
            "'Rust async', 'Kubernetes networking'). Returns titles and snippets."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (be specific and technical)"},
                "max_results": {
                    "type": "integer",
                    "description": "Number of results (default 6, max 10)",
                    "default": 6,
                },
            },
            "required": ["query"],
        },
        handler=_web_search,
        category="search",
        timeout_s=15.0,
    ),
]
