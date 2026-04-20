"""
search_keepa_tool.py
--------------------
Fetches Amazon price data via Keepa API and computes median/average from price
history (NEW, USED, or BUY_BOX_SHIPPING).

Requires:
    export KEEPA_API_KEY=<your key>
    pip install aiohttp
Docs:
    https://keepa.com/#!api
"""

import os, aiohttp, asyncio, statistics, logging, json
from datetime import datetime, timezone
from langchain_core.tools import tool
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger("KeepaTool")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

KEEPA_API = "https://api.keepa.com/product"

# ---------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------
def _extract_recent_prices(csv_data, limit_points: int = 10) -> list[float]:
    """Extract latest nonzero prices from Keepa csv arrays (handles dict or list)."""
    prices = []
    if not csv_data:
        return prices

    # Case 1: Dict style (expected)
    if isinstance(csv_data, dict):
        for key in ("NEW", "USED", "BUY_BOX_SHIPPING"):
            arr = csv_data.get(key)
            if not arr or len(arr) < 2:
                continue
            values = [arr[i + 1] for i in range(0, len(arr) - 1, 2)]
            nonzero = [v / 100 for v in values if isinstance(v, (int, float)) and v > 0]
            if nonzero:
                prices.extend(nonzero[-limit_points:])
        return prices

    # Case 2: List style (some Keepa endpoints return arrays)
    if isinstance(csv_data, list):
        for arr in csv_data:
            if not isinstance(arr, list) or len(arr) < 2:
                continue
            values = [arr[i + 1] for i in range(0, len(arr) - 1, 2)]
            nonzero = [v / 100 for v in values if isinstance(v, (int, float)) and v > 0]
            if nonzero:
                prices.extend(nonzero[-limit_points:])
        return prices

    return prices


# ---------------------------------------------------------------------
# Tool Definition
# ---------------------------------------------------------------------
@tool("search_keepa_tool", return_direct=False)
async def search_keepa_tool(query: str) -> dict:
    """
    Search Keepa for Amazon pricing data.
    Args:
        query: ASIN or UPC.
    Returns:
        dict with median/average new price and metadata.
    """
    api_key = os.getenv("KEEPA_API_KEY")
    if not api_key:
        logger.error("❌ KEEPA_API_KEY not set.")
        return _empty_result(query)

    # Detect ASIN vs UPC
    params = {"key": api_key, "domain": "1", "history": "1"}
    if query.isdigit():
        params["code"] = query
    else:
        params["asin"] = query

    async with aiohttp.ClientSession() as session:
        async with session.get(KEEPA_API, params=params, timeout=25) as r:
            data = await r.json()
            if r.status != 200:
                logger.warning(f"⚠️ Keepa returned {r.status}: {data}")
                return _empty_result(query)

    # Debug output
    if os.getenv("DEBUG_KEEPA", "false").lower() in ("1", "true", "yes"):
        print("\n=== RAW KEEPA RESPONSE (truncated) ===")
        print(json.dumps(data, indent=2)[:2000])
        print("====================================\n")

    products = data.get("products", [])
    if not products:
        logger.info(f"⚠️ No Keepa results for '{query}'")
        return _empty_result(query)

    prices = []
    for p in products:
        csv_data = p.get("csv") or {}
        prices.extend(_extract_recent_prices(csv_data))

        # Also include summary fields if present
        for field in ("buyBoxPrice", "newPrice", "usedPrice"):
            val = p.get(field)
            if isinstance(val, (int, float)) and val > 0:
                prices.append(val / 100)

    if not prices:
        logger.info(f"⚠️ No numeric price values found for '{query}'")
        return _empty_result(query)

    median_price = round(statistics.median(prices), 2)
    avg_price = round(statistics.mean(prices), 2)
    title = products[0].get("title", "Unknown")
    asin = products[0].get("asin")
    upc = (
        (products[0].get("eanList") or [None])[0]
        or (products[0].get("upcList") or [None])[0]
    )

    logger.info(f"💰 Keepa median ${median_price} (avg ${avg_price}) from {len(prices)} points.")

    return {
        "source": "Keepa (Amazon)",
        "query_used": query,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "title": title,
        "asin": asin,
        "upc": upc,
        "sample_count": len(prices),
        "median_price": median_price,
        "average_price": avg_price,
        "source_used": True,
    }


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _empty_result(query: str) -> dict:
    return {
        "source": "Keepa (Amazon)",
        "query_used": query,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sample_count": 0,
        "median_price": None,
        "average_price": None,
        "source_used": False,
    }


# ---------------------------------------------------------------------
# Local Test
# ---------------------------------------------------------------------
if __name__ == "__main__":
    async def _test():
        tests = ["B0D3J97251", "B0DMFG98YS", "887521134595"]
        for q in tests:
            print("\n====================================")
            print(f"🔍 Query: {q}")
            result = await search_keepa_tool.arun(q)
            print(f"✅ Median: {result['median_price']}, Avg: {result['average_price']}")
            print(f"ASIN: {result.get('asin')} | UPC: {result.get('upc')}\n")

    asyncio.run(_test())
