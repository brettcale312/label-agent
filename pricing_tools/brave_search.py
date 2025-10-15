"""
pricing_tools/brave_search.py
-----------------------------
Fallback web pricing via the Brave Search API (free JSON endpoint).
Parses snippets for "$xx.xx" patterns and returns a median/average price.
"""

import os
import re
import requests
from statistics import mean, median
from dotenv import load_dotenv
from utils.logger import get_logger

load_dotenv()
logger = get_logger("brave_search")

BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")
BASE_URL = "https://api.search.brave.com/res/v1/web/search"


def _extract_prices(text: str):
    """Find all $xx.xx patterns and return as floats."""
    return [float(p.replace("$", "")) for p in re.findall(r"\$\s?(\d{1,4}(?:\.\d{1,2})?)", text)]


def get_brave_price(query: str, limit: int = 10):
    """Search Brave API and estimate a market price from snippets."""
    if not BRAVE_API_KEY:
        logger.error("Missing BRAVE_API_KEY in environment.")
        return None

    headers = {"Accept": "application/json", "X-Subscription-Token": BRAVE_API_KEY}
    params = {"q": query, "count": limit}

    try:
        logger.info(f"[Brave] Searching web for {query}")
        resp = requests.get(BASE_URL, headers=headers, params=params, timeout=10)
        if resp.status_code != 200:
            logger.warning(f"[Brave] HTTP {resp.status_code}: {resp.text[:200]}")
            return None

        data = resp.json()
        results = data.get("web", {}).get("results", [])
        if not results:
            logger.info(f"[Brave] No web results for '{query}'")
            return None

        prices = []
        for r in results:
            snippet = " ".join([r.get("title", ""), r.get("description", "")])
            prices += _extract_prices(snippet)

        if not prices:
            logger.info(f"[Brave] No price patterns found for '{query}'")
            return None

        avg_p = round(mean(prices), 2)
        med_p = round(median(prices), 2)
        logger.info(f"[Brave] Found {len(prices)} prices → median {med_p}, avg {avg_p}")
        return med_p

    except Exception as e:
        logger.error(f"[Brave] Error: {e}")
        return None


if __name__ == "__main__":
    print(get_brave_price("Funko Pop Darth Vader"))
