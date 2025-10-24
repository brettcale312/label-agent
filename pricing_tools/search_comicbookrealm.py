"""
search_comicbookrealm.py
------------------------
Wrapper tool for ComicBookRealm searches via smart_search.
"""

from langchain_core.tools import tool
from pricing_tools.smart_search import smart_search


@tool
async def search_comicbookrealm(query: str, limit: int | None = 10) -> dict:
    """
    Search ComicBookRealm for comic values and pricing data.

    Args:
        query: Search query string.
        limit: Max results to return (default 10).

    Returns:
        Normalized dict with 'source', 'query', 'timestamp', and 'results'.
    """
    return await smart_search.arun(query, site="comicbookrealm.com", limit=limit)
