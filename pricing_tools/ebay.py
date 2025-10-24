"""
pricing_tools/ebay.py
---------------------
Async eBay Browse API wrapper for LangGraph Pricing Agent.
Fetches current eBay listing data and computes median price,
filters irrelevant results (graded, signed, slabbed), and removes outliers.
"""

import os
import asyncio
import logging
from typing import Dict, Any, List
import aiohttp
import numpy as np
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
# Helper Functions
# ---------------------------------------------------------------------
def _filter_irrelevant(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove listings that are graded, signed, or bulk lots."""
    banned_keywords = [
        "cgc", "pgx", "cbcs", "slab", "graded", "autograph", "autographed",
        "signed", "signature", "lot", "set of", "bundle", "collection"
    ]
    filtered = []
    for i in items:
        title = (i.get("title") or "").lower()
        if not any(bad in title for bad in banned_keywords):
            filtered.append(i)
    return filtered

def _remove_outliers(prices: List[float]) -> List[float]:
    """Trim outliers using the IQR method (1.5×IQR rule)."""
    if len(prices) < 5:
        return prices
    q1 = np.percentile(prices, 25)
    q3 = np.percentile(prices, 75)
    iqr = q3 - q1
    lower_bound = q1 - 1.5 * iqr
    upper_bound = q3 + 1.5 * iqr
    return [p for p in prices if lower_bound <= p <= upper_bound]

# ---------------------------------------------------------------------
# eBay Tool Definition
# ---------------------------------------------------------------------
@tool("search_ebay")
async def search_ebay(query: str, sold: bool = False) -> Dict[str, Any]:
    """
    Query eBay's Browse API for active listings and return structured pricing data.
    Filters out irrelevant (graded/signed) listings and trims price outliers.
    """
    enable_tool = os.getenv("ENABLE_EBAY_TOOL", "false").lower() == "true"
    if not enable_tool:
        logger.info("[eBayTool] Disabled via environment variable.")
        print("⚠️ eBay disabled. ENABLE_EBAY_TOOL not set.", flush=True)
        return {"source": "eBay", "median_price": None, "sample_count": 0}

    async def _perform_search(access_token: str) -> Dict[str, Any]:
        try:
            params = {
                "q": query,
                "limit": "40",
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
                async with session.get(EBAY_API_URL, headers=headers, params=params, timeout=25) as resp:
                    text = await resp.text()
                    if resp.status == 401:
                        return {"error": "invalid_token"}
                    if resp.status != 200:
                        logger.warning(f"[eBayTool] HTTP {resp.status}: {text[:200]}")
                        return {"error": f"http {resp.status}", "text": text[:200]}
                    return {"data": await resp.json()}
        except Exception as e:
            logger.error(f"[eBayTool] Error during lookup: {e}")
            return {"error": str(e)}

    # --- Get or refresh token ---
    try:
        access_token = get_ebay_access_token()
    except Exception as e:
        logger.error(f"[eBayTool] Failed to retrieve eBay access token: {e}")
        return {"source": "eBay", "error": str(e)}

    # --- Perform search ---
    result = await _perform_search(access_token)
    if result.get("error") == "invalid_token":
        logger.info("[eBayTool] 🔁 Refreshing token and retrying eBay request...")
        access_token = get_ebay_access_token()
        result = await _perform_search(access_token)

    if "error" in result:
        return {"source": "eBay", "median_price": None, "sample_count": 0, "error": result["error"]}

    # --- Process data ---
    data = result.get("data", {})
    items = data.get("itemSummaries", [])

    # Apply title filters
    filtered_items = _filter_irrelevant(items)
    prices = [float(i.get("price", {}).get("value", 0)) for i in filtered_items if i.get("price")]

    if not prices:
        logger.info(f"[eBayTool] No valid prices found for '{query}' after filtering.")
        return {"source": "eBay", "median_price": None, "sample_count": 0, "raw": items[:5]}

    # Remove outliers if enough data
    clean_prices = _remove_outliers(prices)
    if len(clean_prices) != len(prices):
        logger.info(f"[eBayTool] 🔎 Removed {len(prices)-len(clean_prices)} outlier(s).")

    prices = sorted(clean_prices)
    median = round(np.median(prices), 2)
    avg = round(float(np.mean(prices)), 2)

    logger.info(f"[eBayTool] 💰 Median ${median} (avg ${avg}) from {len(prices)} listings after filtering.")
    print(f"💰 eBay median for '{query}': ${median} (avg ${avg}) from {len(prices)} listings.", flush=True)

    if DEBUG_EBAY:
        print("\n--- Sample Listings ---", flush=True)
        for i, item in enumerate(filtered_items[:5]):
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
        "raw": filtered_items[:5],
    }


# ---------------------------------------------------------------------
# Local test
# ---------------------------------------------------------------------
if __name__ == "__main__":
    async def _test():
        os.environ["ENABLE_EBAY_TOOL"] = "true"
        query = "Amazing Spider-Man #31 Near Mint"
        result = await search_ebay(query)
        print("Test result:", result)

    asyncio.run(_test())
