"""
pricing_tools/ebay.py
---------------------
Async eBay Browse API wrapper for LangGraph Pricing Agent.
Fetches current eBay listing data and computes median price.
Automatically refreshes OAuth tokens using ebay_utils.auth.
"""

import os
import asyncio
import logging
from typing import Dict, Any
import aiohttp
from langchain_core.tools import tool
from ebay_utils.auth import get_ebay_access_token

# ---------------------------------------------------------------------
# Logger Setup
# ---------------------------------------------------------------------
logger = logging.getLogger("eBayTool")

if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------
EBAY_API_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
DEBUG_EBAY = os.getenv("DEBUG_EBAY", "false").lower() in ("true", "1", "yes")

# ---------------------------------------------------------------------
# eBay Tool Definition
# ---------------------------------------------------------------------
@tool("search_ebay")
async def search_ebay(query: str, sold: bool = False) -> Dict[str, Any]:
    """
    Query eBay's Browse API for active listings and return structured pricing data.
    Uses automatic token refresh from ebay_utils.auth.
    """
    enable_tool = os.getenv("ENABLE_EBAY_TOOL", "false").lower() == "true"
    if not enable_tool:
        logger.info("[eBayTool] Disabled via environment variable.")
        print("⚠️ eBay disabled. ENABLE_EBAY_TOOL not set.", flush=True)
        return {"source": "eBay", "median_price": None, "sample_count": 0}

    async def _perform_search(access_token: str) -> Dict[str, Any]:
        """Execute a single eBay search call."""
        try:
            params = {
                "q": query,
                "limit": "20",
                "filter": "buyingOptions:FIXED_PRICE",
            }
            headers = {
                "Authorization": f"Bearer {access_token}",
                "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
                "Accept": "application/json",
                "User-Agent": "label-agent/1.0",
            }

            logger.info(f"[eBayTool] 🔍 Searching active listings for '{query}'")
            print(f"🔎 Querying eBay for '{query}' ...", flush=True)

            async with aiohttp.ClientSession() as session:
                async with session.get(EBAY_API_URL, headers=headers, params=params, timeout=20) as resp:
                    text = await resp.text()
                    if resp.status == 401:
                        # Token invalid, trigger refresh
                        logger.warning("[eBayTool] ⚠️ Token invalid — attempting refresh.")
                        return {"error": "invalid_token"}
                    if resp.status != 200:
                        logger.warning(f"[eBayTool] HTTP {resp.status}: {text[:200]}")
                        print(f"⚠️ eBay HTTP {resp.status}: {text[:200]}", flush=True)
                        return {"error": f"http {resp.status}", "text": text[:200]}

                    data = await resp.json()
                    return {"data": data}
        except Exception as e:
            logger.error(f"[eBayTool] Error during lookup: {e}")
            return {"error": str(e)}

    # Get or refresh token automatically
    try:
        access_token = get_ebay_access_token()
    except Exception as e:
        logger.error(f"[eBayTool] Failed to retrieve eBay access token: {e}")
        return {"source": "eBay", "error": str(e)}

    # Perform the initial API call
    result = await _perform_search(access_token)

    # If token invalid, refresh and retry once
    if result.get("error") == "invalid_token":
        logger.info("[eBayTool] 🔁 Refreshing token and retrying eBay request...")
        access_token = get_ebay_access_token()
        result = await _perform_search(access_token)

    # Handle final result
    if "error" in result:
        return {"source": "eBay", "median_price": None, "sample_count": 0, "error": result["error"]}

    data = result.get("data", {})
    items = data.get("itemSummaries", [])
    prices = [
        float(i.get("price", {}).get("value", 0))
        for i in items if i.get("price")
    ]

    if not prices:
        logger.info(f"[eBayTool] No valid prices found for '{query}'")
        print(f"❌ No valid prices found for '{query}'", flush=True)
        return {
            "source": "eBay",
            "median_price": None,
            "sample_count": 0,
            "raw": items[:5],
        }

    prices.sort()
    median = round(prices[len(prices) // 2], 2)
    avg = round(sum(prices) / len(prices), 2)

    logger.info(f"[eBayTool] Found median ${median} (avg ${avg}) from {len(prices)} listings.")
    print(f"💰 eBay median for '{query}': ${median} (avg ${avg}) from {len(prices)} listings.", flush=True)

    if DEBUG_EBAY:
        print("\n--- Sample Listings ---", flush=True)
        for i, item in enumerate(items[:5]):
            title = item.get("title")
            price = item.get("price", {}).get("value")
            url = item.get("itemWebUrl", "")
            print(f"{i+1}. {title} — ${price}\n   {url}", flush=True)
        print("-----------------------\n", flush=True)

    return {
        "source": "eBay",
        "median_price": median,
        "average_price": avg,
        "sample_count": len(prices),
        "raw": items[:5],
    }


# ---------------------------------------------------------------------
# Local test (manual)
# ---------------------------------------------------------------------
if __name__ == "__main__":
    async def _test():
        os.environ["ENABLE_EBAY_TOOL"] = "true"
        query = "Funko Pop Darth Vader"
        result = await search_ebay(query)
        print("Test result:", result)

    asyncio.run(_test())
