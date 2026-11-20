"""Tavily web-search tool factory."""

from __future__ import annotations

from langchain_tavily import TavilySearch

from .config import settings


def get_search_tool() -> TavilySearch:
    """Return a configured Tavily search tool.

    Reads ``TAVILY_API_KEY`` from the environment (populated by ``config``).
    """
    return TavilySearch(
        max_results=settings.max_search_results,
        topic="general",
    )
