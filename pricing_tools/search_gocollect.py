"""
search_gocollect.py
-------------------
Wrapper tool for GoCollect searches via smart_search.
No fallback — returns structured but empty results if nothing found.
"""

import re
import statistics
import logging
from datetime import datetime, UTC
from langchain_core.tools import tool
from pricing_tools.smart_search import smart_search

logger = logging.getLogger("GoCollectTool")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


@tool
async def search_gocollect(query: str, limit: int | None = 10) -> dict:
    """
    Search GoCollect for comic book FMV, graded sales, or market data.

    Args:
        query: Search query string (e.g. "Amazing Spider-Man #300 9.8")
        limit: Max results to return (default 10).

    Returns:
        Normalized dict with unified structure:
        {
            "source": "GoCollect",
            "query": str,
            "timestamp": str,
            "sample_count": int,
            "median_price": float | None,
            "average_price": float | None,
            "grades_detected": list[str],
            "raw": list[dict]
        }
    """
    logger.info(f"[GoCollectTool] 🔍 Searching GoCollect for: {query}")

    # Run the smart search (Brave → Serper → DuckDuckGo)
    data = await smart_search.arun(query, site="gocollect.com", limit=limit)
    all_results = data.get("results", [])

    # Filter to true GoCollect URLs
    results = [r for r in all_results if "gocollect.com" in (r.get("url") or "")]
    if not results:
        logger.warning("[GoCollectTool] ❌ No GoCollect URLs found.")
        return _empty_result(query)

    # Combine all text for scanning
    text_blob = " ".join(
        [r.get("title", "") + " " + r.get("description", "") for r in results]
    )

    # Extract dollar values
    price_matches = re.findall(r"\$[0-9,]+(?:\.[0-9]{2})?", text_blob)
    prices = [
        float(p.replace("$", "").replace(",", ""))
        for p in price_matches
        if p.replace("$", "").replace(",", "").replace(".", "").isdigit()
    ]

    # Extract grades
    grade_matches = re.findall(r"\b(9\.[0-9]|10\.0|8\.[0-9])\b", text_blob)

    if not prices:
        logger.info("[GoCollectTool] ⚠️ No numeric price values detected — returning empty result.")
        return _empty_result(query, grades=grade_matches, results=results)

    median_price = statistics.median(prices)
    avg_price = statistics.mean(prices)

    logger.info(f"[GoCollectTool] 💰 Found {len(prices)} price(s): median=${median_price}, avg=${avg_price}")

    return {
        "source": "GoCollect",
        "query": query,
        "timestamp": datetime.now(UTC).isoformat(),
        "sample_count": len(prices),
        "median_price": median_price,
        "average_price": avg_price,
        "grades_detected": sorted(set(grade_matches)),
        "raw": results[:limit],
        "source_used": bool(median_price or avg_price),
    }


def _empty_result(query: str, grades=None, results=None) -> dict:
    """Return empty structured result for failed/empty searches."""
    return {
        "source": "GoCollect",
        "query": query,
        "timestamp": datetime.now(UTC).isoformat(),
        "sample_count": 0,
        "median_price": None,
        "average_price": None,
        "grades_detected": sorted(set(grades or [])),
        "raw": results or [],
        "source_used": False,
    }


# ---------------------------------------------------------------------
# Local test
# ---------------------------------------------------------------------
if __name__ == "__main__":
    import asyncio

    async def _test():
        query = "Batman 423 9.8"
        result = await search_gocollect(query)
        print("=== GoCollect TEST RESULT ===")
        print(result)

    asyncio.run(_test())
