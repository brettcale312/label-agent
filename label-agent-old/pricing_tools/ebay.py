"""
pricing_tools/ebay.py
---------------------
Async eBay Browse API wrapper for LangGraph Pricing Agent.
Fetches current eBay listing data and computes median price,
filters irrelevant results (graded, signed, slabbed), and removes outliers.
Includes smart category targeting for comics, records, and trading cards,
and supports external Vision-based category hints.
"""

import os
import asyncio
import logging
from typing import Dict, Any, List, Optional
import aiohttp
import numpy as np
from langchain_core.tools import tool
from ebay_utils.auth import get_ebay_access_token
from .value_cleaners import sanitize_prices  # ✅ shared sanitizer

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


def _detect_category(query: str, category_hint: Optional[str] = None) -> Dict[str, Optional[str]]:
    """
    Detect or apply category targeting.
    If category_hint is provided (e.g., 'comic', 'record', 'card'),
    it overrides automatic detection.
    """
    q_lower = query.lower()
    item_type = "general"
    category_id = None

    # External override from vision or caller
    if category_hint:
        hint = category_hint.lower().strip()
        if hint in ("comic", "comics"):
            query += " comic book"
            category_id = "63"
            item_type = "comic"
        elif hint in ("record", "vinyl", "music"):
            query += " vinyl record"
            category_id = "176985"
            item_type = "record"
        elif hint in ("card", "trading card", "tcg"):
            query += " trading card"
            category_id = "183454"
            item_type = "card"
        else:
            item_type = hint
        logger.info(f"[eBayTool] 🎯 Category hint used: {category_hint} → {item_type}")
    else:
        # Automatic detection if no hint given
        if any(k in q_lower for k in ["comic", "#", "variant", "marvel", "dc", "idw", "image", "dark horse"]):
            query += " comic book"
            category_id = "63"
            item_type = "comic"
        elif any(k in q_lower for k in ["vinyl", "record", "lp", "45rpm", "33rpm", "12\"", "7\""]):
            query += " vinyl record"
            category_id = "176985"
            item_type = "record"
        elif any(k in q_lower for k in ["pokemon", "yugioh", "yu-gi-oh", "magic", "mtg", "tcg", "trading card", "booster", "binder", "panini", "topps"]):
            query += " trading card"
            category_id = "183454"
            item_type = "card"

    # Apply exclusion filters for common false positives
    exclude_terms = ["figure", "statue", "toy", "funko", "pop", "lego"]
    if any(t in q_lower for t in exclude_terms):
        query += " -figure -statue -toy -funko -pop -lego"

    logger.info(f"[eBayTool] 🧭 Detected category: {item_type} | category_id={category_id or 'None'} | query='{query}'")
    return {"query": query, "category_id": category_id, "item_type": item_type}


# ---------------------------------------------------------------------
# eBay Tool Definition
# ---------------------------------------------------------------------
@tool("search_ebay")
async def search_ebay(query: str, sold: bool = False, category_hint: Optional[str] = None) -> Dict[str, Any]:
    """
    Query eBay's Browse API for active listings and return structured pricing data.
    Filters out irrelevant (graded/signed) listings and trims price outliers.
    Adds smart category targeting for comics, records, and trading cards.

    Args:
        query: The search string (title, issue, etc.)
        sold: Whether to target sold listings (currently unused).
        category_hint: Optional string ('comic', 'record', 'card', etc.)
                       to override automatic category detection.
    """
    enable_tool = os.getenv("ENABLE_EBAY_TOOL", "false").lower() == "true"
    if not enable_tool:
        logger.info("[eBayTool] Disabled via environment variable.")
        print("⚠️ eBay disabled. ENABLE_EBAY_TOOL not set.", flush=True)
        return {"source": "eBay", "median_price": None, "sample_count": 0}

    # --- Detect item type and refine query ---
    cat_info = _detect_category(query, category_hint)
    refined_query = cat_info["query"]
    category_id = cat_info["category_id"]

    async def _perform_search(access_token: str) -> Dict[str, Any]:
        try:
            params = {
                "q": refined_query,
                "limit": "40",
                "filter": "buyingOptions:FIXED_PRICE",
            }
            if category_id:
                params["category_ids"] = category_id

            headers = {
                "Authorization": f"Bearer {access_token}",
                "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
                "Accept": "application/json",
                "User-Agent": "label-agent/1.0",
            }

            logger.info(f"[eBayTool] 🔍 Searching active listings for '{refined_query}'")
            print(f"🔎 Querying eBay for '{refined_query}' ...", flush=True)

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

    filtered_items = _filter_irrelevant(items)
    prices = [float(i.get("price", {}).get("value", 0)) for i in filtered_items if i.get("price")]

    if not prices:
        logger.info(f"[eBayTool] No valid prices found for '{refined_query}' after filtering.")
        return {"source": "eBay", "median_price": None, "sample_count": 0, "raw": items[:5]}

    # ✅ Centralized cleaning and outlier removal
    prices = sanitize_prices(prices, query=refined_query)

    if not prices:
        logger.info(f"[eBayTool] All prices removed as outliers for '{refined_query}'.")
        return {"source": "eBay", "median_price": None, "sample_count": 0}

    median = round(np.median(prices), 2)
    avg = round(float(np.mean(prices)), 2)

    logger.info(f"[eBayTool] 💰 Median ${median} (avg ${avg}) from {len(prices)} listings after sanitization.")
    print(f"💰 eBay median for '{refined_query}': ${median} (avg ${avg}) from {len(prices)} listings.", flush=True)

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
        "category": cat_info["item_type"],
        "raw": filtered_items[:5],
        "source_used": bool(median or avg),
    }


# ---------------------------------------------------------------------
# Local test (manual run)
# ---------------------------------------------------------------------
if __name__ == "__main__":
    async def _test():
        os.environ["ENABLE_EBAY_TOOL"] = "true"
        tests = [
            ("Amazing Spider-Man #31 Near Mint", None),
            ("Pink Floyd The Wall vinyl LP", "record"),
            ("Pokemon Charizard holo card", "card"),
            ("Vintage Coca-Cola thermometer", None),
        ]
        for q, hint in tests:
            print("\n====================================")
            print(f"Testing: {q} (hint={hint})")
            result = await search_ebay.arun(q, category_hint=hint)   # ✅ .arun instead of direct call
            print("Result:", result)

    asyncio.run(_test())
