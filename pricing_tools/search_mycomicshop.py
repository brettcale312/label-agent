"""
search_mycomicshop.py
---------------------
Wrapper tool for MyComicShop searches via smart_search.
Returns structured price data based on visible retail listings.
"""

import re
import statistics
import logging
from datetime import datetime, UTC
from langchain_core.tools import tool
from pricing_tools.smart_search import smart_search

logger = logging.getLogger("MyComicShopTool")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


@tool
async def search_mycomicshop(query: str, limit: int | None = 10) -> dict:
    """
    Search MyComicShop for issue availability and pricing.

    Args:
        query: Search query string (e.g. "Amazing Spider-Man #300")
        limit: Max results to return (default 10).

    Returns:
        Normalized dict with unified structure:
        {
            "source": "MyComicShop",
            "query": str,
            "timestamp": str,
            "sample_count": int,
            "median_price": float | None,
            "average_price": float | None,
            "conditions_detected": list[str],
            "raw": list[dict]
        }
    """
    logger.info(f"[MyComicShopTool] 🔍 Searching MyComicShop for: {query}")

    # Run smart search (Brave → Serper → DuckDuckGo)
    data = await smart_search.arun(f"site:mycomicshop.com {query}", limit=limit)
    all_results = data.get("results", [])

    # Filter URLs that point to real issue pages
    results = [r for r in all_results if "mycomicshop.com" in (r.get("url") or "")]
    if not results:
        logger.warning("[MyComicShopTool] ❌ No MyComicShop URLs found.")
        return _empty_result(query)

    # Combine text fields
    text_blob = " ".join(
        [r.get("title", "") + " " + r.get("description", "") for r in results]
    )

    # Extract prices (handles $, commas, and decimal formats)
    price_matches = re.findall(r"\$[0-9,]+(?:\.[0-9]{2})?", text_blob)
    prices = [
        float(p.replace("$", "").replace(",", ""))
        for p in price_matches
        if p.replace("$", "").replace(",", "").replace(".", "").isdigit()
    ]

    # Extract common condition abbreviations (VF, NM, FN, GD, etc.)
    cond_matches = re.findall(r"\b(VF|NM|FN|GD|FR|VG|PR|FAIR|GOOD|FINE|MINT)\b", text_blob, re.IGNORECASE)
    cond_matches = [c.upper() for c in cond_matches]

    if not prices:
        logger.info("[MyComicShopTool] ⚠️ No numeric price values detected — returning empty result.")
        return _empty_result(query, cond_matches, results)

    median_price = statistics.median(prices)
    avg_price = statistics.mean(prices)

    logger.info(f"[MyComicShopTool] 💰 Found {len(prices)} price(s): median=${median_price}, avg=${avg_price}")

    return {
        "source": "MyComicShop",
        "query": query,
        "timestamp": datetime.now(UTC).isoformat(),
        "sample_count": len(prices),
        "median_price": median_price,
        "average_price": avg_price,
        "conditions_detected": sorted(set(cond_matches)),
        "raw": results[:limit],
        "source_used": bool(median_price or avg_price),
    }


def _empty_result(query: str, conditions=None, results=None) -> dict:
    """Return empty structured result for failed/empty searches."""
    return {
        "source": "MyComicShop",
        "query": query,
        "timestamp": datetime.now(UTC).isoformat(),
        "sample_count": 0,
        "median_price": None,
        "average_price": None,
        "conditions_detected": sorted(set(conditions or [])),
        "raw": results or [],
        "source_used": False,
    }


# ---------------------------------------------------------------------
# Local test
# ---------------------------------------------------------------------
if __name__ == "__main__":
    import asyncio

    async def _test():
        query = "Batman 423"
        result = await search_mycomicshop(query)
        print("=== MyComicShop TEST RESULT ===")
        print(result)

    asyncio.run(_test())
