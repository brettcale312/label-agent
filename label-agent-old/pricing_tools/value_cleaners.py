"""
value_cleaners.py
-----------------
Shared utilities for cleaning and normalizing price lists across scrapers.
"""

import statistics
import re
import logging

logger = logging.getLogger("ValueCleaners")


def sanitize_prices(prices: list[float], query: str = "") -> list[float]:
    """
    Cleans a list of numeric prices before computing medians or averages.

    Steps:
    - Removes 0, negatives, and non-numeric junk
    - Applies category-aware range limits
    - Removes IQR outliers (top/bottom 5–10%)
    - Trims top/bottom 1 entry on long lists
    """
    prices = [p for p in prices if isinstance(p, (int, float))]
    prices = [p for p in prices if 1 <= p <= 10000]
    if not prices:
        return []

    q = query.lower()

    # Category-based ranges
    if any(k in q for k in ["gameboy", "nes", "playstation", "sega", "game"]):
        low, high = 3, 400
    elif "comic" in q:
        low, high = 2, 2000
    elif any(k in q for k in ["card", "pokemon", "tcg", "mtg"]):
        low, high = 0.25, 500
    elif "vinyl" in q or "record" in q:
        low, high = 2, 300
    else:
        low, high = 1, 2000

    prices = [p for p in prices if low <= p <= high]
    if len(prices) < 4:
        return prices

    # IQR-based outlier filter
    try:
        q1, q3 = statistics.quantiles(prices, n=4)[0], statistics.quantiles(prices, n=4)[2]
        iqr = q3 - q1
        lower_bound = max(low, q1 - 1.5 * iqr)
        upper_bound = min(high, q3 + 1.5 * iqr)
        prices = [p for p in prices if lower_bound <= p <= upper_bound]
    except Exception as e:
        logger.warning(f"[sanitize_prices] IQR failed: {e}")

    if len(prices) > 10:
        prices.sort()
        prices = prices[1:-1]

    return prices
