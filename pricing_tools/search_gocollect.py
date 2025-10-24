"""
search_gocollect.py
-------------------
Wrapper tool for GoCollect searches via smart_search.
"""

from langchain_core.tools import tool
from pricing_tools.smart_search import smart_search


@tool
async def search_gocollect(query: str, limit: int | None = 10) -> dict:
    """
    Search GoCollect for comic book prices, graded sales, and market trends.

    Args:
        query: Search query string.
        limit: Max results to return (default 10).

    Returns:
        Normalized dict with 'source', 'query', 'timestamp', and 'results'.
    """
    return await smart_search.arun(query, site="gocollect.com", limit=limit)
