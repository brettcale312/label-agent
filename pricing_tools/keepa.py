"""
pricing_tools/keepa.py
----------------------
Wrapper for Keepa's public REST API.

Fetches Amazon product data and returns a clean, minimal price snapshot.
Requires one environment variable:  KEEPA_API_KEY
"""

import os
import aiohttp
import asyncio

from statistics import mean

KEEPA_API_KEY = os.getenv("KEEPA_API_KEY")
BASE_URL = "https://api.keepa.com/product"


async def get_keepa_price(asin: str, domain: int = 1) -> dict:
    """
    Query Keepa for product info by ASIN and return a simplified price result.

    Args:
        asin (str): Amazon ASIN (e.g., 'B0D3J97251')
        domain (int): Amazon domain code (1 = US, 3 = UK, etc.)

    Returns:
        dict: {
            "asin": str,
            "title": str,
            "buy_box_price": float or None,
            "avg_90d_price": float or None,
            "used_price": float or None,
            "source": "Keepa"
        }
        or {} if not found or error.
    """
    if not KEEPA_API_KEY:
        raise RuntimeError("Missing KEEPA_API_KEY in environment variables.")

    params = {
        "key": KEEPA_API_KEY,
        "domain": domain,
        "asin": asin,
        "stats": 90,  # include 90-day stats for averages
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(BASE_URL, params=params, timeout=15) as resp:
                if resp.status != 200:
                    print(f"[Keepa] HTTP {resp.status} for ASIN {asin}")
                    return {}
                data = await resp.json()

        if not data.get("products"):
            return {}

        product = data["products"][0]
        title = product.get("title", "Unknown Title")
        stats = product.get("stats", {})

        # Prices are returned in cents → divide by 100
        buy_box = stats.get("buyBoxPrice") / 100 if stats.get("buyBoxPrice") else None
        new_price = stats.get("current")[-1] / 100 if stats.get("current") else None
        avg_90d = stats.get("avg90") / 100 if stats.get("avg90") else None
        used_price = stats.get("used") / 100 if stats.get("used") else None

        # Choose the most relevant available number
        price_candidates = [p for p in (buy_box, new_price, avg_90d) if p]
        final_price = round(mean(price_candidates), 2) if price_candidates else None

        return {
            "asin": asin,
            "title": title,
            "buy_box_price": buy_box,
            "avg_90d_price": avg_90d,
            "used_price": used_price,
            "price": final_price,
            "source": "Keepa",
        }

    except Exception as e:
        print(f"[Keepa] Error fetching {asin}: {e}")
        return {}


# --- Quick local test ---
if __name__ == "__main__":
    async def test():
        result = await get_keepa_price("B0D3J97251")
        print(result)

    asyncio.run(test())
