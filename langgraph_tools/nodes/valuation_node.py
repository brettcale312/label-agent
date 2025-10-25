"""
valuation_node.py
-----------------
Applies deterministic valuation logic based on weighted market data.
"""

from pricing_tools.valuation_logic import round_retail
from utils.logger import get_logger

logger = get_logger("valuation_node")

def valuation_node(market_data: dict, reasoning: dict, item_meta: dict) -> dict:
    """Blend sources using reasoning weights and apply venue multipliers."""
    ebay = market_data.get("ebay", {})
    discogs = market_data.get("discogs", {})

    ebay_price = ebay.get("median") or ebay.get("price") or 0
    discogs_price = discogs.get("median") or discogs.get("price") or 0

    e_w = reasoning.get("ebay_weight", 0.7)
    d_w = reasoning.get("discogs_weight", 0.3)
    base_price = (ebay_price * e_w + discogs_price * d_w)

    venue = item_meta.get("venue", "antique_store").lower()
    condition = item_meta.get("condition", "vg").lower()

    if base_price < 5:
        base_price = 5.0

    # Venue-specific multipliers
    if venue == "antique_store":
        if base_price < 5:
            base_price *= 2.5
        elif base_price < 10:
            base_price *= 1.75
        else:
            base_price *= 1.2
    elif venue == "ebay":
        base_price *= 1.0
    elif venue == "record_show":
        base_price *= 1.3

    final_price = round_retail(base_price, venue)

    return {
        "estimated_price": final_price,
        "ebay_weight": e_w,
        "discogs_weight": d_w,
        "venue": venue,
        "condition": condition,
        "ebay_price": ebay_price,
        "discogs_price": discogs_price,
    }
