"""
Async eBay API wrapper for LangGraph Pricing Agent.
"""

import os
import asyncio
import logging
from typing import Dict, Any
import aiohttp

logger = logging.getLogger("eBayTool")

EBAY_API_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"


async def search_ebay(query: str, sold: bool = False) -> Dict[str, Any]:
    """
    Query eBay's Browse API for item summaries and return structured pricing data.
    If ENABLE_EBAY_TOOL is not true, returns a placeholder result.
    """
    if not os.getenv("ENABLE_EBAY_TOOL", "false").lower() == "true":
        logger.info("[eBayTool] Disabled via environment variable.")
        return {"source": "eBay", "median_price": None, "sample_count": 0}

    try:
        params = {"q": query}
        headers = {"Authorization": f"Bearer {os.getenv('EBAY_ACCESS_TOKEN', '')}"}

        async with aiohttp.ClientSession() as session:
            async with session.get(EBAY_API_URL, headers=headers, params=params) as resp:
                data = await resp.json()

                items = data.get("itemSummaries", [])
                prices = [
                    float(i.get("price", {}).get("value", 0))
                    for i in items if i.get("price")
                ]

                if not prices:
                    return {
                        "source": "eBay",
                        "median_price": None,
                        "sample_count": 0,
                        "raw": [],
                    }

                prices.sort()
                median = round(prices[len(prices) // 2], 2)

                logger.info(
                    f"[eBayTool] Found median price ${median} from {len(prices)} samples."
                )

                return {
                    "source": "eBay",
                    "median_price": median,
                    "sample_count": len(prices),
                    "raw": items[:5],
                }

    except Exception as e:
        logger.error(f"[eBayTool] Error during lookup: {e}")
        return {"source": "eBay", "error": str(e)}
