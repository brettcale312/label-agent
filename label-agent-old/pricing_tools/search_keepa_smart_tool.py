"""
search_keepa_smart_tool.py
--------------------------
Smart Keepa integration for Amazon listings.
Accepts ASIN, UPC, or keyword queries — automatically searches and fetches pricing data.

✨ Features:
    • Detects ASIN / UPC / keyword automatically.
    • Uses Keepa API search for keywords.
    • Parses csv price history for NEW/USED/BUY_BOX.
    • Returns ASIN, UPC, title, brand, and unified price metrics.

Requires:
    export KEEPA_API_KEY=<your key>
    pip install aiohttp python-dotenv
Docs:
    https://keepa.com/#!api
"""

import os, aiohttp, asyncio, statistics, logging, json
from datetime import datetime, timezone
from langchain_core.tools import tool
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger("KeepaSmartTool")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

BASE_URL = "https://api.keepa.com"
DOMAIN = "1"  # 1 = amazon.com (US)

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
async def keepa_request(endpoint: str, params: dict) -> dict:
    """Generic Keepa API request wrapper."""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{BASE_URL}/{endpoint}", params=params, timeout=30) as r:
            text = await r.text()
            if r.status != 200:
                logger.warning(f"⚠️ Keepa {endpoint} returned {r.status}: {text[:200]}")
                return {}
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                logger.error(f"❌ JSON decode error for Keepa {endpoint}")
                return {}

def _extract_recent_prices(csv_data, limit_points: int = 10) -> list[float]:
    """Extract latest nonzero prices (handles dict or list)."""
    prices = []
    if not csv_data:
        return prices

    if isinstance(csv_data, dict):
        for key in ("NEW", "USED", "BUY_BOX_SHIPPING"):
            arr = csv_data.get(key)
            if not arr or len(arr) < 2:
                continue
            vals = [arr[i + 1] for i in range(0, len(arr) - 1, 2)]
            nonzero = [v / 100 for v in vals if isinstance(v, (int, float)) and v > 0]
            if nonzero:
                prices.extend(nonzero[-limit_points:])
        return prices

    if isinstance(csv_data, list):
        for arr in csv_data:
            if not isinstance(arr, list) or len(arr) < 2:
                continue
            vals = [arr[i + 1] for i in range(0, len(arr) - 1, 2)]
            nonzero = [v / 100 for v in vals if isinstance(v, (int, float)) and v > 0]
            if nonzero:
                prices.extend(nonzero[-limit_points:])
        return prices

    return prices

# ---------------------------------------------------------------------
# Main Tool
# ---------------------------------------------------------------------
@tool("search_keepa_smart_tool", return_direct=False)
async def search_keepa_smart_tool(query: str) -> dict:
    """
    Smart Keepa search supporting ASIN, UPC, and keyword.
    """
    api_key = os.getenv("KEEPA_API_KEY")
    if not api_key:
        logger.error("❌ KEEPA_API_KEY not set.")
        return _empty_result(query)

    asin = None
    products = []
    metadata = {}

    # -------------------------------------------------------------
    # Detect type (ASIN / UPC / keyword)
    # -------------------------------------------------------------
    if len(query) == 10 and query.isalnum():
        asin = query.upper()
        logger.info(f"[KeepaSmart] 🧭 Detected ASIN: {asin}")
    elif query.isdigit() and len(query) in (12, 13):
        logger.info(f"[KeepaSmart] 🧭 Detected UPC: {query}")
        params = {"key": api_key, "domain": DOMAIN, "code": query, "history": "1"}
        data = await keepa_request("product", params)
        products = data.get("products", [])
    else:
        logger.info(f"[KeepaSmart] 🔍 Keyword search: {query}")
        params = {"key": api_key, "domain": DOMAIN, "type": "product", "term": query, "page": 0}
        search_data = await keepa_request("search", params)
        if not search_data or not search_data.get("products"):
            logger.warning(f"[KeepaSmart] ⚠️ No Keepa results for '{query}'")
            return _empty_result(query)
        asin = search_data["products"][0].get("asin")
        logger.info(f"[KeepaSmart] ✅ Found ASIN {asin} for '{query}'")

    # -------------------------------------------------------------
    # Fetch details if ASIN present but no products loaded
    # -------------------------------------------------------------
    if asin and not products:
        params = {"key": api_key, "domain": DOMAIN, "asin": asin, "history": "1"}
        data = await keepa_request("product", params)
        products = data.get("products", [])

    if not products:
        return _empty_result(query)

    # -------------------------------------------------------------
    # Parse price arrays and metadata
    # -------------------------------------------------------------
    prices = []
    for p in products:
        csv_data = p.get("csv")
        prices.extend(_extract_recent_prices(csv_data))

        # Add summary price fields
        for field in ("buyBoxPrice", "newPrice", "usedPrice"):
            val = p.get(field)
            if isinstance(val, (int, float)) and val > 0:
                prices.append(val / 100)

        if not metadata:
            metadata = {
                "asin": p.get("asin"),
                "title": p.get("title"),
                "brand": p.get("brand"),
                "upc": (
                    ", ".join(p.get("upcList", []))
                    if p.get("upcList")
                    else (", ".join(p.get("eanList", [])) if p.get("eanList") else None)
                ),
                "url": f"https://www.amazon.com/dp/{p.get('asin')}" if p.get("asin") else None,
            }

    if not prices:
        logger.info(f"[KeepaSmart] ⚠️ No numeric price values found for '{query}'")
        return _empty_result(query, metadata)

    # Clean and compute stats
    prices = sorted([p for p in prices if p > 0])
    trimmed = prices[1:-1] if len(prices) > 4 else prices
    median_price = round(statistics.median(trimmed), 2)
    avg_price = round(statistics.mean(trimmed), 2)

    logger.info(f"[KeepaSmart] 💰 Median ${median_price}, Avg ${avg_price}, from {len(trimmed)} points")

    return {
        "source": "Keepa (Amazon)",
        "query_used": query,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sample_count": len(trimmed),
        "median_price": median_price,
        "average_price": avg_price,
        "metadata": metadata,
        "source_used": True,
    }

# ---------------------------------------------------------------------
# Empty result
# ---------------------------------------------------------------------
def _empty_result(query: str, metadata=None) -> dict:
    return {
        "source": "Keepa (Amazon)",
        "query_used": query,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sample_count": 0,
        "median_price": None,
        "average_price": None,
        "metadata": metadata or {},
        "source_used": False,
    }

# ---------------------------------------------------------------------
# Local test
# ---------------------------------------------------------------------
if __name__ == "__main__":
    async def _test():
        tests = [
            "B0D3J97251",        # ASIN
            "887521134595",      # UPC
            "Star Wars Black Series Qui-Gon Obi-Wan Maul",  # keyword
        ]
        for q in tests:
            print("\n====================================")
            print(f"🔍 Query: {q}")
            result = await search_keepa_smart_tool.arun(q)
            print(f"✅ Median: {result['median_price']}, Avg: {result['average_price']}")
            if result["metadata"]:
                print("🧾", json.dumps(result["metadata"], indent=2))
    asyncio.run(_test())
