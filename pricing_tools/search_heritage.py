"""
search_heritage.py
------------------
Wrapper tool for searching Heritage Auctions via smart_search.
"""

from langchain_core.tools import tool
from pricing_tools.smart_search import smart_search


@tool
async def search_heritage(query: str, limit: int | None = 10) -> dict:
    """
    Search Heritage Auctions (comics.ha.com) for comic or collectible listings.

    Args:
        query: Search query string.
        limit: Max results to return (default 10).

    Returns:
        Normalized dict with 'source', 'query', 'timestamp', and 'results'.
    """
    return await smart_search.arun(query, site="comics.ha.com", limit=limit)
