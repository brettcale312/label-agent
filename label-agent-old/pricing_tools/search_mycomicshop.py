"""
pricing_tools/search_mycomicshop.py
-----------------------------------
SmartSearch-based MyComicShop price extractor.
Performs lightweight scraping via Brave/DuckDuckGo (no Playwright).
Includes number sanitization, outlier removal, and unified structure.
"""

import re
import statistics
import numpy as np
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


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _clean_price(text: str) -> float | None:
    """Extract a clean numeric price value from a string."""
    if not text:
        return None
    match = re.search(r"\$([\d,]+(?:\.\d{1,2})?)", text)
    if match:
        try:
            return float(match.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


def _remove_outliers(prices: list[float]) -> list[float]:
    """Remove outliers using IQR (1.5× rule)."""
    if len(prices) < 5:
        return prices
    q1, q3 = np.percentile(prices, [25, 75])
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    filtered = [p for p in prices if lower <= p <= upper]
    if len(filtered) != len(prices):
        logger.info(f"[MyComicShopTool] 🧹 Removed {len(prices) - len(filtered)} outlier(s).")
    return filtered


# ---------------------------------------------------------------------
# Main Tool
# ---------------------------------------------------------------------
@tool("search_mycomicshop", return_direct=False)
async def search_mycomicshop(query: str, limit: int | None = 10) -> dict:
    """
    Search MyComicShop for issue availability and pricing.

    Args:
        query: Search query string (e.g. "Amazing Spider-Man #300")
        limit: Max results to return (default 10).

    Returns:
        Normalized dict with unified structure.
    """
    logger.info(f"[MyComicShopTool] 🔍 Searching MyComicShop for: {query}")

    data = await smart_search.arun(f"site:mycomicshop.com {query}", limit=limit)
    all_results = data.get("results", [])

    # Keep only MyComicShop results
    results = [r for r in all_results if "mycomicshop.com" in (r.get("url") or "")]
    if not results:
        logger.warning("[MyComicShopTool] ❌ No MyComicShop URLs found.")
        return _empty_result(query)

    # Combine text for extraction
    text_blob = " ".join(
        [r.get("title", "") + " " + r.get("description", "") for r in results]
    )

    # Extract and clean price values
    raw_prices = re.findall(r"\$[\d,]+(?:\.\d{2})?", text_blob)
    prices = [_clean_price(p) for p in raw_prices if _clean_price(p) is not None]

    # Detect condition abbreviations (NM, VF, FN, etc.)
    cond_matches = re.findall(
        r"\b(VF|NM|FN|GD|FR|VG|PR|FAIR|GOOD|FINE|MINT)\b",
        text_blob,
        re.IGNORECASE,
    )
    cond_matches = [c.upper() for c in cond_matches]

    if not prices:
        logger.info("[MyComicShopTool] ⚠️ No numeric prices detected.")
        return _empty_result(query, cond_matches, results)

    # Remove outliers and compute stats
    clean_prices = _remove_outliers(prices)
    median_price = round(float(np.median(clean_prices)), 2)
    avg_price = round(float(np.mean(clean_prices)), 2)

    logger.info(f"[MyComicShopTool] 💰 Found {len(clean_prices)} price(s): median=${median_price}, avg=${avg_price}")

    return {
        "source": "MyComicShop",
        "query": query,
        "timestamp": datetime.now(UTC).isoformat(),
        "sample_count": len(clean_prices),
        "median_price": median_price,
        "average_price": avg_price,
        "conditions_detected": sorted(set(cond_matches)),
        "raw": results[:limit],
        "source_used": bool(median_price or avg_price),
    }


# ---------------------------------------------------------------------
# Empty result
# ---------------------------------------------------------------------
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
    import sys

    async def _test():
        if len(sys.argv) > 1:
            queries = [sys.argv[1]]
        else:
            queries = [
                "Amazing Spider-Man #300",
                "Batman 423",
                "X-Men #266",
            ]
        for q in queries:
            print("\n====================================")
            print(f"🔍 Query: {q}")
            result = await search_mycomicshop.arun(q)
            print(f"✅ {result['sample_count']} prices found")
            print(f"💰 Median: ${result['median_price']}")
            print(f"📊 Average: ${result['average_price']}")

    asyncio.run(_test())
