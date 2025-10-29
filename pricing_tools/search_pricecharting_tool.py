"""
search_pricecharting_tool.py
----------------------------
Fetches pricing data from PriceCharting's API (supports trading cards, games, comics, etc.)

Requires:
    export PRICECHARTING_API_KEY=<your key>
    pip install aiohttp python-dotenv

Docs:
    https://www.pricecharting.com/api-documentation
"""

import os
import aiohttp
import asyncio
import logging
import statistics
from datetime import datetime, timezone
from langchain_core.tools import tool
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger("PriceChartingTool")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

API_URL = "https://www.pricecharting.com/api/product"


@tool("search_pricecharting_tool", return_direct=False)
async def search_pricecharting_tool(query: str) -> dict:
    """
    Search PriceCharting API for a product by name, UPC, or keyword.
    Returns low/mid/high price estimates with median + average.
    """
    api_key = os.getenv("PRICECHARTING_API_KEY")
    if not api_key:
        logger.error("❌ PRICECHARTING_API_KEY not set in .env")
        return _empty_result(query)

    params = {"t": api_key, "q": query}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(API_URL, params=params, timeout=20) as r:
                if r.status != 200:
                    logger.warning(f"⚠️ PriceCharting returned {r.status}")
                    return _empty_result(query)
                data = await r.json()

    except Exception as e:
        logger.error(f"❌ Error fetching PriceCharting data: {e}")
        return _empty_result(query)

    if not data or "product-name" not in data:
        logger.warning(f"⚠️ No PriceCharting result for '{query}'")
        return _empty_result(query)

    # Extract and normalize (API returns prices in cents)
    low = _normalize_price(data.get("loose-price"))
    mid = _normalize_price(data.get("cib-price"))
    high = _normalize_price(data.get("new-price"))

    prices = [p for p in (low, mid, high) if p is not None]
    if not prices:
        return _empty_result(query)

    median_price = round(statistics.median(prices), 2)
    avg_price = round(statistics.mean(prices), 2)

    title = data.get("product-name", "Unknown")
    url = data.get("url", f"https://www.pricecharting.com/search-products?q={query}")

    logger.info(f"💰 {title} | Low ${low} | Mid ${mid} | High ${high} | Median ${median_price}")

    return {
        "source": "PriceCharting",
        "query_used": query,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "title": title,
        "sample_count": len(prices),
        "low_price": low,
        "mid_price": mid,
        "high_price": high,
        "median_price": median_price,
        "average_price": avg_price,
        "url": url,
        "source_used": True,
    }


def _normalize_price(value):
    """Convert to float and adjust for cents → dollars."""
    try:
        val = float(value)
        return round(val / 100, 2)
    except (TypeError, ValueError):
        return None


def _empty_result(query: str) -> dict:
    return {
        "source": "PriceCharting",
        "query_used": query,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sample_count": 0,
        "low_price": None,
        "mid_price": None,
        "high_price": None,
        "median_price": None,
        "average_price": None,
        "url": None,
        "source_used": False,
    }


# ---------------------------------------------------------------------
# Local test
# ---------------------------------------------------------------------
if __name__ == "__main__":
    async def _test():
        tests = [
            "Charizard Base Set Holo 4/102",
            "Final Fantasy VII PS1",
            "Miraidon ex 253/198",
        ]
        for q in tests:
            print("\n====================================")
            print(f"🔍 Query: {q}")
            result = await search_pricecharting_tool.arun(q)
            print(f"✅ Median: {result['median_price']}, Avg: {result['average_price']}")
            print(f"💲 Low={result['low_price']} Mid={result['mid_price']} High={result['high_price']}")
            print("🔗", result["url"])

    asyncio.run(_test())
