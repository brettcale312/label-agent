"""
pricing_tools/discogs.py
------------------------
Discogs API wrapper for fetching release and pricing data.

Requires a personal access token (DISCOGS_TOKEN) set in .env.
Automatically retries on rate limits and timeouts,
iterates through multiple editions to find valid price data,
and supports global DEBUG_LOGS for detailed output.
"""

import os
import aiohttp
import asyncio
from statistics import median
from dotenv import load_dotenv
from utils.logger import get_logger

# --- Setup ---
load_dotenv()
BASE_URL = "https://api.discogs.com"
DISCOGS_TOKEN = os.getenv("DISCOGS_TOKEN")
DEBUG_LOGS = os.getenv("DEBUG_LOGS", "false").lower() in ("true", "1", "yes")
logger = get_logger("discogs")


async def _fetch_json(session: aiohttp.ClientSession, url: str, params: dict = None, retries: int = 2):
    """Helper with retries for API GET requests."""
    headers = {}
    if DISCOGS_TOKEN:
        headers["Authorization"] = f"Discogs token={DISCOGS_TOKEN}"
        headers["User-Agent"] = "pricing-agent/1.0"

    for attempt in range(retries):
        try:
            async with session.get(url, params=params, headers=headers, timeout=10) as resp:
                if resp.status == 429:
                    logger.warning(f"Rate limited on {url}, sleeping before retry...")
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


async def _async_discogs_lookup(query: str, limit: int = 10) -> dict:
    """
    Search Discogs for a record/CD/cassette and return median or lowest marketplace price.
    Iterates through multiple editions and returns the one with the most listings.
    """
    if not DISCOGS_TOKEN:
        logger.error("Missing DISCOGS_TOKEN in environment. Please add it to your .env file.")
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

        best_result = None
        best_num_for_sale = 0

        for release in results:
            release_id = release.get("id")
            if not release_id:
                continue

            detail_url = f"{BASE_URL}/marketplace/stats/{release_id}"
            stats = await _fetch_json(session, detail_url)
            if not stats:
                continue

            # Safely coerce num_for_sale
            try:
                num_for_sale = int(stats.get("num_for_sale") or 0)
            except (TypeError, ValueError):
                num_for_sale = 0

            # Parse lowest/median prices
            lowest_price = None
            lp_data = stats.get("lowest_price")
            if isinstance(lp_data, dict):
                lowest_price = lp_data.get("value")
            elif isinstance(lp_data, (int, float)):
                lowest_price = lp_data

            median_price = None
            if "price" in stats and isinstance(stats["price"], dict):
                median_price = stats["price"].get("median") or stats["price"].get("median_price")
                if not lowest_price and stats["price"].get("lowest"):
                    lowest_price = stats["price"]["lowest"]

            if stats.get("blocked_from_sale"):
                continue

            if DEBUG_LOGS:
                logger.info(
                    f"Candidate: {release.get('title')} — "
                    f"{num_for_sale} for sale, lowest: {lowest_price}, median: {median_price}"
                )

            if num_for_sale > 0 and (median_price or lowest_price):
                if num_for_sale > best_num_for_sale:
                    artist_data = release.get("artist") or release.get("label", "")
                    if isinstance(artist_data, list):
                        artist_data = ", ".join(str(a) for a in artist_data)

                    best_result = {
                        "title": release.get("title"),
                        "artist": artist_data,
                        "year": release.get("year"),
                        "median_price": median_price,
                        "lowest_price": lowest_price,
                        "sample_count": num_for_sale,
                        "source": "Discogs",
                    }
                    best_num_for_sale = num_for_sale

        if not best_result:
            logger.info(f"No release with price data found for '{query}'")
            return {}

        logger.info(f"Success: {best_result}")
        return best_result


def get_discogs_price(title: str, artist: str = None):
    """
    Synchronous wrapper for pricing_model.py
    Runs the async Discogs lookup and returns a numeric price (float or None).
    """
    try:
        query = f"{title} {artist or ''}".strip()
        result = asyncio.run(_async_discogs_lookup(query, limit=10))
        if not result:
            return None
        # Prefer median price if available, else lowest
        return result.get("median_price") or result.get("lowest_price")
    except Exception as e:
        logger.error(f"[Discogs] Error in wrapper: {e}")
        return None


# --- Local Test ---
if __name__ == "__main__":
    price = get_discogs_price("Taylor Swift Midnights Vinyl")
    print(f"Discogs price: {price}")
