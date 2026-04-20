"""
pricing.py
----------
Queries PriceCharting and eBay concurrently for card pricing data.
Both sources are optional — if either fails or returns no results,
the system falls back to Claude's knowledge-based estimate in valuation.py.

Adapted from label-agent/pricing_tools/search_pricecharting_tool.py and ebay.py.
No LangChain dependency.
"""

import os
import asyncio
import base64
import logging
import re
import statistics
import time
import requests
import aiohttp
from typing import Optional

logger = logging.getLogger("pricing")

# ─────────────────────────────────────────────────────────────────────────────
# PriceCharting
# ─────────────────────────────────────────────────────────────────────────────

PRICECHARTING_API_URL = "https://www.pricecharting.com/api/product"


def _pc_normalize(value) -> Optional[float]:
    """PriceCharting returns prices in cents."""
    try:
        return round(float(value) / 100, 2)
    except (TypeError, ValueError):
        return None


# Words that are too generic to use for match validation
_PC_STOPWORDS = {
    "the", "a", "an", "of", "in", "and", "or", "set", "card", "pokemon",
    "holo", "rare", "base", "scarlet", "violet", "ex", "gx", "vmax", "v",
    "common", "uncommon", "promo", "foil", "trading",
}


def _is_pc_match(query: str, product_name: str) -> bool:
    """
    Validate that PriceCharting's returned product name is actually the card
    we searched for. PriceCharting always returns something — this prevents
    accepting a wrong card that happened to share a number.

    Rule: at least one significant word from the query must appear in the
    returned product name (case-insensitive, ignoring stopwords).
    """
    def significant_words(text: str) -> set[str]:
        words = re.sub(r"[^a-z0-9 ]", " ", text.lower()).split()
        return {w for w in words if w not in _PC_STOPWORDS and len(w) > 2}

    query_words = significant_words(query)
    product_words = significant_words(product_name)

    if not query_words:
        return True  # nothing to validate against

    overlap = query_words & product_words
    matched = len(overlap) > 0
    if not matched:
        logger.warning(
            f"[PC] Match rejected — query words {query_words} "
            f"vs returned '{product_name}' (words: {product_words})"
        )
    return matched


async def fetch_pricecharting(query: str) -> Optional[float]:
    """
    Query PriceCharting API. Returns median of low/mid/high prices, or None.
    """
    api_key = os.getenv("PRICECHARTING_API_KEY")
    if not api_key:
        logger.info("[PC] PRICECHARTING_API_KEY not set — skipping")
        return None

    params = {"t": api_key, "q": query}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(PRICECHARTING_API_URL, params=params, timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status != 200:
                    logger.warning(f"[PC] HTTP {r.status} for '{query}'")
                    return None
                data = await r.json()
    except Exception as e:
        logger.warning(f"[PC] Request error for '{query}': {e}")
        return None

    if not data or "product-name" not in data:
        logger.info(f"[PC] No result for '{query}'")
        return None

    product_name = data.get("product-name", "")

    # Reject results where the returned card name doesn't match our query
    if not _is_pc_match(query, product_name):
        logger.info(f"[PC] Discarding '{product_name}' — not a match for '{query}'")
        return None

    low = _pc_normalize(data.get("loose-price"))
    mid = _pc_normalize(data.get("cib-price"))
    high = _pc_normalize(data.get("new-price"))

    prices = [p for p in (low, mid, high) if p is not None]
    if not prices:
        return None

    median = round(statistics.median(prices), 2)
    logger.info(f"[PC] '{product_name}' → low={low} mid={mid} high={high} median={median}")
    return median


# ─────────────────────────────────────────────────────────────────────────────
# eBay OAuth token (inline, no LangChain dependency)
# ─────────────────────────────────────────────────────────────────────────────

_EBAY_TOKEN_CACHE: dict = {"token": None, "expires_at": 0}


def _get_ebay_token() -> Optional[str]:
    client_id = os.getenv("EBAY_CLIENT_ID") or os.getenv("EBAY_APP_ID")
    client_secret = os.getenv("EBAY_CLIENT_SECRET") or os.getenv("EBAY_CERT_ID")
    refresh_token = os.getenv("EBAY_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        logger.warning("[eBay] Missing credentials (EBAY_CLIENT_ID/SECRET/REFRESH_TOKEN)")
        return None

    if _EBAY_TOKEN_CACHE["token"] and time.time() < _EBAY_TOKEN_CACHE["expires_at"]:
        return _EBAY_TOKEN_CACHE["token"]

    creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    try:
        r = requests.post(
            "https://api.ebay.com/identity/v1/oauth2/token",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {creds}",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": "https://api.ebay.com/oauth/api_scope",
            },
            timeout=10,
        )
        r.raise_for_status()
        td = r.json()
        _EBAY_TOKEN_CACHE["token"] = td["access_token"]
        _EBAY_TOKEN_CACHE["expires_at"] = time.time() + td.get("expires_in", 7200) - 60
        return _EBAY_TOKEN_CACHE["token"]
    except Exception as e:
        logger.warning(f"[eBay] Auth error: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# eBay price sanitizer (adapted from value_cleaners.py)
# ─────────────────────────────────────────────────────────────────────────────

def _sanitize_prices(prices: list[float]) -> list[float]:
    prices = [p for p in prices if isinstance(p, (int, float)) and 0.25 <= p <= 500]
    if len(prices) < 4:
        return prices
    try:
        q1 = statistics.quantiles(prices, n=4)[0]
        q3 = statistics.quantiles(prices, n=4)[2]
        iqr = q3 - q1
        prices = [p for p in prices if (q1 - 1.5 * iqr) <= p <= (q3 + 1.5 * iqr)]
    except Exception:
        pass
    if len(prices) > 10:
        prices = sorted(prices)[1:-1]
    return prices


EBAY_API_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
_BANNED_KEYWORDS = {"cgc", "pgx", "cbcs", "slab", "graded", "autograph",
                    "signed", "signature", "lot", "set of", "bundle", "collection"}


async def fetch_ebay(query: str) -> Optional[float]:
    """
    Query eBay Browse API for active fixed-price card listings.
    Returns median price from filtered results, or None.
    """
    if os.getenv("ENABLE_EBAY_TOOL", "true").lower() != "true":
        logger.info("[eBay] Disabled via ENABLE_EBAY_TOOL")
        return None

    token = _get_ebay_token()
    if not token:
        return None

    search_query = f"{query} trading card"

    params = {
        "q": search_query,
        "limit": "40",
        "filter": "buyingOptions:FIXED_PRICE",
        "category_ids": "183454",  # Trading Cards category
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        "Accept": "application/json",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                EBAY_API_URL, headers=headers, params=params,
                timeout=aiohttp.ClientTimeout(total=25)
            ) as resp:
                if resp.status == 401:
                    # Token expired — clear cache and skip (will refresh next call)
                    _EBAY_TOKEN_CACHE["token"] = None
                    logger.warning("[eBay] 401 — token expired, will refresh on next call")
                    return None
                if resp.status != 200:
                    logger.warning(f"[eBay] HTTP {resp.status} for '{search_query}'")
                    return None
                data = await resp.json()
    except Exception as e:
        logger.warning(f"[eBay] Request error: {e}")
        return None

    items = data.get("itemSummaries", [])

    # Filter graded/signed/bulk
    filtered = [
        i for i in items
        if not any(bad in (i.get("title") or "").lower() for bad in _BANNED_KEYWORDS)
    ]

    prices = []
    for item in filtered:
        try:
            prices.append(float(item["price"]["value"]))
        except (KeyError, TypeError, ValueError):
            pass

    prices = _sanitize_prices(prices)
    if not prices:
        logger.info(f"[eBay] No valid prices for '{search_query}'")
        return None

    median = round(statistics.median(prices), 2)
    logger.info(f"[eBay] '{search_query}' → median=${median} from {len(prices)} listings")
    return median


# ─────────────────────────────────────────────────────────────────────────────
# Combined fetch (run both concurrently)
# ─────────────────────────────────────────────────────────────────────────────

async def fetch_market_prices(search_query: str) -> tuple[Optional[float], Optional[float]]:
    """
    Run PriceCharting and eBay concurrently.
    Returns (pricecharting_median, ebay_median). Either may be None.
    """
    pc_task = fetch_pricecharting(search_query)
    ebay_task = fetch_ebay(search_query)

    results = await asyncio.gather(pc_task, ebay_task, return_exceptions=True)

    pc_median = results[0] if not isinstance(results[0], Exception) else None
    ebay_median = results[1] if not isinstance(results[1], Exception) else None

    logger.info(f"[pricing] Results — PriceCharting: {pc_median}, eBay: {ebay_median}")
    return pc_median, ebay_median
