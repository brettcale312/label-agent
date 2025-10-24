"""
smart_search.py
---------------
Unified search layer for the Market Agent.
Tries Brave Search first, then Serper.dev (Google), then DuckDuckGo.
"""

import os
import logging
import aiohttp
from dotenv import load_dotenv
from langchain_core.tools import tool
from duckduckgo_search import DDGS

load_dotenv()
logger = logging.getLogger("smart_search")


async def brave_search(query: str) -> dict | None:
    """Query the Brave Search API."""
    url = "https://api.search.brave.com/res/v1/web/search"
    key = os.getenv("BRAVE_API_KEY")
    if not key:
        logger.warning("BRAVE_API_KEY not set; skipping Brave search.")
        return None

    headers = {"Accept": "application/json", "X-Subscription-Token": key}
    params = {"q": query, "count": 10}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params=params, headers=headers) as r:
                if r.status == 200:
                    data = await r.json()
                    return {"source": "brave", "query": query, "results": data.get("web", {}).get("results", [])}
                else:
                    logger.warning(f"Brave API error {r.status}")
                    return None
    except Exception as e:
        logger.error(f"Brave search failed: {e}")
        return None


async def serper_search(query: str) -> dict | None:
    """Query the Serper.dev (Google) Search API."""
    url = "https://google.serper.dev/search"
    key = os.getenv("SERPER_API_KEY")
    if not key:
        logger.warning("SERPER_API_KEY not set; skipping Serper search.")
        return None

    headers = {"X-API-KEY": key}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(url, json={"q": query}, headers=headers) as r:
                if r.status == 200:
                    data = await r.json()
                    return {"source": "serper", "query": query, "results": data.get("organic", [])}
                else:
                    logger.warning(f"Serper API error {r.status}")
                    return None
    except Exception as e:
        logger.error(f"Serper search failed: {e}")
        return None


async def duckduckgo_search(query: str) -> dict | None:
    """Query DuckDuckGo (no key required)."""
    results = []
    try:
        async with DDGS() as ddgs:
            async for r in ddgs.text(query, max_results=10):
                results.append({"title": r.get("title"), "href": r.get("href"), "snippet": r.get("body")})
        return {"source": "duckduckgo", "query": query, "results": results}
    except Exception as e:
        logger.error(f"DuckDuckGo search failed: {e}")
        return None


@tool
async def smart_search(query: str, site: str | None = None) -> dict:
    """
    Smart multi-tiered search tool.
    Tries Brave → Serper → DuckDuckGo in that order.
    Optionally restricts search to a specific site.
    """
    full_query = f"site:{site} {query}" if site else query
    logger.info(f"[smart_search] Searching for: {full_query}")

    for search_func in (brave_search, serper_search, duckduckgo_search):
        result = await search_func(full_query)
        if result and result.get("results"):
            logger.info(f"[smart_search] ✅ {result['source']} returned {len(result['results'])} results.")
            return result

    logger.warning("[smart_search] ❌ No results from any provider.")
    return {"source": "none", "query": full_query, "results": []}
