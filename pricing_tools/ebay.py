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
        "filter": "buyingOptions:{FIXED_PRICE}",
        "fieldgroups": "ASPECT_REFINEMENTS",
    }

    headers = {
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        "Authorization": f"Bearer {EBAY_TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "pricing-agent/1.0",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(BROWSE_API_URL, params=params, headers=headers, timeout=20) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    msg = f"HTTP {resp.status}: {text[:400]}"
                    logger.warning(f"[eBay] {msg}")
                    if DEBUG_LOGS:
                        print(msg)
                    return {}

                data = await resp.json()

        items = data.get("itemSummaries", [])
        if not items:
            logger.info(f"No items found for query '{q}'")
            if DEBUG_LOGS:
                print(f"No items found for '{q}'")
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
        "filter": "buyingOptions:{FIXED_PRICE}",
    }

    headers = {
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        "Authorization": f"Bearer {EBAY_TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "pricing-agent/1.0",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(BROWSE_API_URL, params=params, headers=headers, timeout=20) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    msg = f"HTTP {resp.status}: {text[:400]}"
                    logger.warning(f"[eBay] {msg}")
                    if DEBUG_LOGS:
                        print(msg)
                    return []

                data = await resp.json()

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


# === Local test ===
if __name__ == "__main__":
    async def test():
        print("=== Price Summary ===")
        result = await get_ebay_active_price(query="Funko Pop Darth Vader")
        print(result)

        print("\n=== Sample Listings ===")
        listings = await get_ebay_listings(query="Funko Pop Darth Vader", limit=5)
        for item in listings:
            print(f"{item['title']} — {item['price']} {item['currency']} ({item['condition']})")
            print(item['url'])
            print()

    asyncio.run(test())
