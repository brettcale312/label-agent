"""
utils/extractors.py
-------------------
Reusable helpers for extracting numeric price data and computing statistics
from normalized search results (e.g., smart_search, eBay, GoCollect, Discogs).

Features:
- Robust $xx.xx pattern extraction
- Automatic outlier trimming for larger samples
- Summary stats: min, max, median, average, count
"""

import re
from statistics import mean, median
from typing import List, Dict, Any, Optional


PRICE_PATTERN = re.compile(r"\$\s?(\d{1,5}(?:[\.,]\d{1,2})?)", re.IGNORECASE)


# ------------------------------------------------------------
# Core extraction helpers
# ------------------------------------------------------------
def extract_prices_from_text(text: str) -> List[float]:
    """
    Extract all $xx.xx-style price values from text.
    Returns list of floats (may be empty).
    """
    if not text:
        return []

    values: List[float] = []
    for match in PRICE_PATTERN.findall(text):
        try:
            values.append(float(match.replace(",", "").strip()))
        except ValueError:
            continue
    return values


def extract_prices_from_results(results: List[Dict[str, Any]]) -> List[float]:
    """
    Scan a list of normalized result dicts and collect numeric prices
    found in title, snippet, and priceRange fields.
    """
    prices: List[float] = []
    for r in results:
        snippet_parts = [
            r.get("title"),
            r.get("snippet"),
            r.get("priceRange"),
            str(r.get("price") or "")
        ]
        text = " ".join(filter(None, snippet_parts))
        prices.extend(extract_prices_from_text(text))
    return prices


# ------------------------------------------------------------
# Outlier handling
# ------------------------------------------------------------
def trim_outliers(prices: List[float], lower_pct: float = 0.1, upper_pct: float = 0.1) -> List[float]:
    """
    Remove extreme outliers by discarding the lowest and highest percentiles.
    Only applies if sample size > 10; otherwise returns unchanged list.
    """
    if len(prices) <= 10:
        return prices

    prices_sorted = sorted(prices)
    n = len(prices_sorted)
    lower_index = int(n * lower_pct)
    upper_index = int(n * (1 - upper_pct))
    trimmed = prices_sorted[lower_index:upper_index]

    return trimmed if trimmed else prices_sorted


# ------------------------------------------------------------
# Summary statistics
# ------------------------------------------------------------
def summarize_prices(prices: List[float]) -> Optional[Dict[str, Any]]:
    """
    Compute statistics from a list of numeric prices.
    Automatically trims outliers for large samples.
    Returns dict with min, max, median, average, count.
    """
    if not prices:
        return None

    trimmed = trim_outliers(prices)
    return {
        "count": len(prices),
        "trimmed_count": len(trimmed),
        "min": round(min(trimmed), 2),
        "max": round(max(trimmed), 2),
        "median": round(median(trimmed), 2),
        "average": round(mean(trimmed), 2),
        "outlier_trimmed": len(prices) != len(trimmed)
    }


def estimate_price_from_results(results: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Convenience function: from normalized search results → summarized price stats.
    """
    prices = extract_prices_from_results(results)
    return summarize_prices(prices)
