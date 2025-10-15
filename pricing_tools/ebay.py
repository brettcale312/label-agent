"""
pricing_tools/ebay.py
---------------------
Modern eBay Browse API wrapper (active listings only).
Fetches current eBay listing data via the Browse API
and computes median and average price.
Also provides a helper to retrieve raw listing data
and logs key events via the shared logger.
"""

import os
import aiohttp
import asyncio
from statistics import median, mean
from dotenv import load_dotenv
from ebay_utils.auth import get_ebay_access_token
from utils.logger import get_logger
import json

# Initialize unified logger
logger = get_logger("ebay")

# Load environment variables
load_dotenv()
DEBUG_LOGS = os.getenv("DEBUG_LOGS", "false").lower() in ("true", "1", "yes")

# eBay Browse API endpoint
BROWSE_API_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"


# === Core pricing function ===
async def get_ebay_active_price(query: str = None, upc: str = None, limit: int = 20) -> dict:
    """
    Search eBay's Browse API for active listings and return median + average price.
    Uses live market data (active listings), not sold/completed items.
    """
    if not query and not upc:
        raise ValueError("Either 'query' or 'upc' must be provided.")

    try:
        EBAY_TOKEN = get_ebay_access_token()
    except Exception as e:
        logger.error(f"Failed to obtain eBay token: {e}")
        raise

    q = query or upc
    params = {
        "q": q,
        "limit": str(limit),
        "filter": "buyingOptions:FIXED_PRICE",
        # removed fieldgroups to prevent empty results
    }

    headers = {
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        "Authorization": f"Bearer {EBAY_TOKEN}",
        "Accept": "application/json",
        "User-Agent": "pricing-agent/1.0",
    }

    logger.info(f"[eBay] GET {BROWSE_API_URL}  params={params}")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(BROWSE_API_URL, params=params, headers=headers, timeout=20) as resp:
                text = await resp.text()
                if resp.status != 200:
                    msg = f"HTTP {resp.status}: {text[:400]}"
                    logger.warning(f"[eBay] {msg}")
                    if DEBUG_LOGS:
                        print(msg)
                    return {}

                data = {}
                try:
                    data = json.loads(text)
                except Exception:
                    logger.error("Failed to parse eBay JSON response")
                    if DEBUG_LOGS:
                        print("Response snippet:", text[:500])
                    return {}

        items = data.get("itemSummaries", [])
        if not items:
            logger.info(f"No items found for query '{q}'")
            if DEBUG_LOGS:
                print("🔍 Raw eBay response snippet:", json.dumps(data, indent=2)[:800])
            return {}

        prices = []
        for item in items:
            try:
                value = float(item.get("price", {}).get("value", 0))
                if value > 0:
                    prices.append(value)
            except Exception:
                continue

        if not prices:
            logger.info(f"No valid prices for query '{q}'")
            if DEBUG_LOGS:
                print(f"No valid prices for '{q}'")
            return {}

        med = round(median(prices), 2)
        avg = round(mean(prices), 2)
        title = items[0].get("title", q)

        result = {
            "median_price": med,
            "average_price": avg,
            "sample_count": len(prices),
            "title_match": title,
            "source": "eBay Browse API (Active Listings)",
        }

        logger.info(f"Retrieved {len(prices)} listings for '{q}' (median: {med}, avg: {avg})")
        if DEBUG_LOGS:
            print(f"✅ {q}: median={med}, avg={avg}, {len(prices)} listings")

        return result

    except Exception as e:
        msg = f"Error during eBay API call: {e}"
        logger.error(msg)
        if DEBUG_LOGS:
            print(msg)
        return {}


# === Listing details helper ===
async def get_ebay_listings(query: str = None, upc: str = None, limit: int = 10) -> list:
    """
    Return a list of active eBay listings for a given keyword or UPC.
    Includes title, price, condition, URL, and seller.
    """
    if not query and not upc:
        raise ValueError("Either 'query' or 'upc' must be provided.")

    EBAY_TOKEN = get_ebay_access_token()
    q = query or upc

    params = {
        "q": q,
        "limit": str(limit),
        "filter": "buyingOptions:FIXED_PRICE",
    }

    headers = {
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        "Authorization": f"Bearer {EBAY_TOKEN}",
        "Accept": "application/json",
        "User-Agent": "pricing-agent/1.0",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(BROWSE_API_URL, params=params, headers=headers, timeout=20) as resp:
                text = await resp.text()
                if resp.status != 200:
                    msg = f"HTTP {resp.status}: {text[:400]}"
                    logger.warning(f"[eBay] {msg}")
                    if DEBUG_LOGS:
                        print(msg)
                    return []

                data = {}
                try:
                    data = json.loads(text)
                except Exception:
                    logger.error("Failed to parse eBay JSON response")
                    if DEBUG_LOGS:
                        print("Response snippet:", text[:500])
                    return []

        items = data.get("itemSummaries", [])
        results = []
        for item in items:
            price_info = item.get("price", {})
            results.append({
                "title": item.get("title"),
                "price": price_info.get("value"),
                "currency": price_info.get("currency"),
                "condition": item.get("condition"),
                "url": item.get("itemWebUrl"),
                "seller": (item.get("seller") or {}).get("username"),
            })

        logger.info(f"Retrieved {len(results)} raw listings for '{q}'")
        if DEBUG_LOGS:
            print(f"✅ Retrieved {len(results)} raw listings for '{q}'")

        return results

    except Exception as e:
        msg = f"Listing fetch error: {e}"
        logger.error(msg)
        if DEBUG_LOGS:
            print(msg)
        return []


# === Synchronous wrapper for pricing_model ===
def get_ebay_price(title: str, category: str = None):
    """
    Synchronous wrapper used by pricing_model.py
    Runs the async eBay Browse API and returns a numeric price.
    Prefers median price if available.
    """
    try:
        query = f"{title} {category or ''}".strip()
        result = asyncio.run(get_ebay_active_price(query=query, limit=20))
        if not result:
            return None
        return result.get("median_price") or result.get("average_price")
    except Exception as e:
        logger.error(f"[eBay] Error in wrapper: {e}")
        return None


# === Local test ===
if __name__ == "__main__":
    price = get_ebay_price("Funko Pop Darth Vader")
    print(f"eBay price: {price}")
