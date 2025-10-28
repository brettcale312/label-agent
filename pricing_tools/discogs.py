"""
pricing_tools/discogs.py
------------------------
Discogs API wrapper for fetching release and pricing data.

Stable version (no marketplace/search fallback).
Uses only /marketplace/stats for completed-sales data.
Returns normalized fields for LangGraph agent compatibility.
"""

import os, sys, asyncio, aiohttp
from dotenv import load_dotenv
from langchain_core.tools import tool
from utils.logger import get_logger

# --- setup so direct execution works ---
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

# ---------------------------------------------------------------------------
# Environment setup
# ---------------------------------------------------------------------------
load_dotenv()
BASE_URL = "https://api.discogs.com"
DISCOGS_TOKEN = os.getenv("DISCOGS_TOKEN")
DEBUG_LOGS = os.getenv("DEBUG_LOGS", "false").lower() in ("true", "1", "yes")
logger = get_logger("discogs")


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------
async def _fetch_json(session: aiohttp.ClientSession, url: str, params: dict = None, retries: int = 2):
    """Helper with retries for API GET requests."""
    headers = {"User-Agent": "pricing-agent/1.0", "Accept": "application/json"}
    if DISCOGS_TOKEN:
        headers["Authorization"] = f"Discogs token={DISCOGS_TOKEN}"

    for attempt in range(retries):
        try:
            async with session.get(url, params=params, headers=headers, timeout=10) as resp:
                if resp.status == 429:
                    logger.warning(f"Rate limited {resp.status} on {url}, sleeping {2**attempt}s before retry...")
                    await asyncio.sleep(2 ** attempt)
                    continue
                if resp.status != 200:
                    logger.warning(f"Non-200 response ({resp.status}) for {url}")
                    return {}
                return await resp.json()
        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching {url} (attempt {attempt + 1})")
            await asyncio.sleep(2 ** attempt)
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return {}
    return {}


# ---------------------------------------------------------------------------
# Core Discogs lookup
# ---------------------------------------------------------------------------
async def _async_discogs_lookup(query: str, limit: int = 10) -> dict:
    """
    Search Discogs for a record/CD/cassette and return:
    title, artist, year, median_price, lowest_price, sample_count.
    """
    if not DISCOGS_TOKEN:
        logger.error("Missing DISCOGS_TOKEN in environment. Add it to your .env file.")
        return {}

    search_url = f"{BASE_URL}/database/search"
    params = {"q": query, "type": "release", "per_page": limit}
    logger.info(f"Searching for '{query}'")

    async with aiohttp.ClientSession() as session:
        data = await _fetch_json(session, search_url, params=params)
        results = data.get("results", [])
        if not results:
            logger.info(f"No results for '{query}'")
            return {}

        best_result, best_num_for_sale = None, 0

        for release in results:
            release_id = release.get("id")
            if not release_id:
                continue

            stats_url = f"{BASE_URL}/marketplace/stats/{release_id}"
            stats = await _fetch_json(session, stats_url)
            if not stats:
                continue

            try:
                num_for_sale = int(stats.get("num_for_sale") or 0)
            except (TypeError, ValueError):
                num_for_sale = 0

            # extract lowest & median
            lowest_price, median_price = None, None
            lp_data = stats.get("lowest_price")
            if isinstance(lp_data, dict):
                lowest_price = lp_data.get("value")
            elif isinstance(lp_data, (int, float)):
                lowest_price = lp_data

            price_data = stats.get("price")
            if isinstance(price_data, dict):
                median_price = price_data.get("median") or price_data.get("median_price")
                if not lowest_price and price_data.get("lowest"):
                    lowest_price = price_data["lowest"]

            if stats.get("blocked_from_sale"):
                continue

            if DEBUG_LOGS:
                logger.info(
                    f"Candidate: {release.get('title')} — "
                    f"{num_for_sale} for sale, lowest: {lowest_price}, median: {median_price}"
                )

            # pick best record with valid price data
            if num_for_sale > 0 and (median_price or lowest_price):
                if num_for_sale > best_num_for_sale:
                    artist_data = release.get("artist") or release.get("label", "")
                    if isinstance(artist_data, list):
                        artist_data = ", ".join(str(a) for a in artist_data)

                    best_result = {
                        "title": release.get("title"),
                        "artist": artist_data,
                        "year": release.get("year"),
                        "median_price": median_price or lowest_price,
                        "lowest_price": lowest_price,
                        "sample_count": num_for_sale,
                        "source": "Discogs",
                        "source_used": bool(median_price or lowest_price),
                    }
                    best_num_for_sale = num_for_sale

        if not best_result:
            logger.info(f"No release with price data found for '{query}'")
            return {}

        # ensure a fallback median
        if not best_result.get("median_price") and best_result.get("lowest_price"):
            best_result["median_price"] = best_result["lowest_price"]

        logger.info(f"Success: {best_result}")
        return best_result


# ---------------------------------------------------------------------------
# Synchronous helper
# ---------------------------------------------------------------------------
def get_discogs_price(title: str, artist: str = None):
    """Sync wrapper for quick local test."""
    try:
        query = f"{title} {artist or ''}".strip()
        result = asyncio.run(_async_discogs_lookup(query, limit=10))
        if not result:
            return None
        return result.get("median_price") or result.get("lowest_price")
    except Exception as e:
        logger.error(f"[Discogs] Error in wrapper: {e}")
        return None


# ---------------------------------------------------------------------------
# LangGraph tool wrapper (normalized output)
# ---------------------------------------------------------------------------
@tool("search_discogs")
async def search_discogs_tool(query: str) -> dict:
    """
    LangGraph tool: Search Discogs for a record/CD/cassette by title or artist.
    Returns normalized price data compatible with other pricing tools.
    """
    try:
        result = await _async_discogs_lookup(query)
        if not result:
            return {
                "source": "Discogs",
                "title": query,
                "price": None,
                "median": None,
                "average": None,
                "samples": 0,
                "error": f"No Discogs data found for '{query}'",
                "source_used": False,
            }

        median_price = result.get("median_price")
        lowest_price = result.get("lowest_price")
        samples = result.get("sample_count", 0)
        price_val = median_price or lowest_price

        return {
            "source": "Discogs",
            "title": result.get("title"),
            "artist": result.get("artist"),
            "year": result.get("year"),
            "price": price_val,
            "median": median_price,
            "average": median_price or lowest_price,
            "samples": samples,
            "source_used": bool(price_val),
        }
    except Exception as e:
        logger.error(f"[DiscogsTool] {e}")
        return {
            "source": "Discogs",
            "title": query,
            "price": None,
            "median": None,
            "average": None,
            "samples": 0,
            "error": str(e),
        }


# ---------------------------------------------------------------------------
# Local test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    price = get_discogs_price("Chicago Transit Authority", "Chicago")
    print(f"Discogs price: {price}")
