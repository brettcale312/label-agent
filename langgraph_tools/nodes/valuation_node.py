"""
valuation_node.py
-----------------
Computes the final collectible value from all market sources.

Consumes:
  • market_data (from reasoning_node)
  • reasoning (weights + comments)
  • current_item (condition, venue, category, etc.)

This version:
  ✅ Supports PriceCharting and Keepa weighting
  ✅ Retains booth rounding and venue multipliers
  ✅ Adapts to category and condition
  ✅ Logs full source breakdown
"""

from typing import Dict, Any
from utils.logger import get_logger

logger = get_logger("valuation_node")


# ---------------------------------------------------------------------
# Rounding helper
# ---------------------------------------------------------------------
def apply_booth_rounding(value: float) -> float:
    """Apply Robyn’s final booth rounding rule."""
    if value <= 0:
        return 0.0
    if value < 1:
        return 1.00
    elif value < 5:
        quarters = value * 4
        rounded_up = (int(quarters) + (0 if quarters.is_integer() else 1)) / 4
        return round(rounded_up, 2)
    else:
        return float(int(value) + (0 if value.is_integer() else 1))


# ---------------------------------------------------------------------
# Valuation Node
# ---------------------------------------------------------------------
async def valuation_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Compute the final price using weighted medians and condition multipliers."""

    market = state.get("market_data", {})
    reasoning = state.get("reasoning", {})
    current_item = state.get("current_item", {}) or {}
    item_type = current_item.get("type", "").lower()

    if not market:
        logger.warning("[ValuationNode] ⚠️ No market_data; cannot compute value.")
        return {**state, "valuation": {"final_price": 0.0}}

    logger.info(f"[ValuationNode] 🧮 Valuation start for {current_item.get('title', 'Unknown Item')}")

    # -----------------------------------------------------------------
    # Extract prices
    # -----------------------------------------------------------------
    def get_price(src):
        d = market.get(src, {}) or {}
        return d.get("median") or d.get("average") or 0.0

    ebay_price = get_price("ebay")
    discogs_price = get_price("discogs")
    mcs_price = get_price("mycomicshop")
    pc_price = get_price("pricecharting")
    keepa_price = get_price("keepa (amazon)") or get_price("keepa")

    # -----------------------------------------------------------------
    # Pull reasoning weights (with defaults)
    # -----------------------------------------------------------------
    e_w = reasoning.get("ebay_weight", 0.3)
    d_w = reasoning.get("discogs_weight", 0.1)
    mcs_w = reasoning.get("mcs_weight", 0.1)
    pc_w = reasoning.get("pricecharting_weight", 0.4)
    k_w = reasoning.get("keepa_weight", 0.1)

    # Normalize to 1.0
    total = e_w + d_w + mcs_w + pc_w + k_w
    if total == 0:
        e_w = 1.0
        total = 1.0
    e_w, d_w, mcs_w, pc_w, k_w = [x / total for x in (e_w, d_w, mcs_w, pc_w, k_w)]

    # -----------------------------------------------------------------
    # Category rules (PriceCharting priority)
    # -----------------------------------------------------------------
    if item_type in ("comic", "card", "video game", "funko", "collectible"):
        # Prefer PriceCharting when present
        if pc_price > 0:
            pc_w, e_w, mcs_w = 0.7, 0.2, 0.1
        elif mcs_price > 0:
            pc_w, e_w, mcs_w = 0.0, 0.4, 0.6
        else:
            e_w, d_w, mcs_w, pc_w, k_w = 1.0, 0, 0, 0, 0

    elif item_type in ("record", "vinyl"):
        # Records → both eBay + Discogs
        if discogs_price > 0:
            e_w, d_w = 0.6, 0.4
        else:
            e_w, d_w = 1.0, 0.0
        pc_w = mcs_w = k_w = 0.0

    elif item_type in ("toy", "sealed", "modern collectible"):
        if keepa_price > 0:
            k_w, e_w = 0.6, 0.4
        else:
            e_w = 1.0
        pc_w = d_w = mcs_w = 0.0

    # Normalize again
    total = e_w + d_w + mcs_w + pc_w + k_w
    e_w, d_w, mcs_w, pc_w, k_w = [x / total for x in (e_w, d_w, mcs_w, pc_w, k_w)]

    # -----------------------------------------------------------------
    # Compute weighted base price
    # -----------------------------------------------------------------
    base_price = (
        (ebay_price * e_w)
        + (discogs_price * d_w)
        + (mcs_price * mcs_w)
        + (pc_price * pc_w)
        + (keepa_price * k_w)
    )

    logger.info(
        f"📊 Source mix → eBay={e_w:.2f}, Discogs={d_w:.2f}, MCS={mcs_w:.2f}, "
        f"PriceCharting={pc_w:.2f}, Keepa={k_w:.2f}"
    )
    logger.info(
        f"💰 Raw medians → eBay={ebay_price}, Discogs={discogs_price}, "
        f"MCS={mcs_price}, PC={pc_price}, Keepa={keepa_price} → base={base_price:.2f}"
    )

    # -----------------------------------------------------------------
    # Venue / condition multipliers
    # -----------------------------------------------------------------
    venue = (current_item.get("venue") or "").lower()
    condition = (current_item.get("condition") or "").lower()
    category = (current_item.get("category") or item_type).lower()

    # Booth/antique markups
    if venue in ("antique_mall", "antique_store", "booth"):
        if base_price < 10:
            base_price *= 1.75
        elif base_price < 30:
            base_price *= 1.35
        else:
            base_price *= 1.2
    elif venue in ("online", "ebay", "etsy", "shopify"):
        base_price *= 1.05

    # Category adjustments
    if "vinyl" in category or "record" in category:
        base_price *= 1.1
    elif "comic" in category:
        base_price *= 1.15
    elif "card" in category:
        base_price *= 1.05

    # Condition adjustments
    if "sealed" in condition:
        base_price *= 1.3
    elif "mint" in condition or "nm" in condition:
        base_price *= 1.1
    elif "poor" in condition or "fair" in condition:
        base_price *= 0.6

    # -----------------------------------------------------------------
    # Final rounding and output
    # -----------------------------------------------------------------
    if base_price <= 0:
        base_price = 5.00
    else:
        base_price = apply_booth_rounding(base_price)

    result = {
        "final_price": float(base_price),
        "source_summary": {
            "ebay_price": ebay_price,
            "discogs_price": discogs_price,
            "mcs_price": mcs_price,
            "pricecharting_price": pc_price,
            "keepa_price": keepa_price,
            "weights": {
                "ebay": e_w,
                "discogs": d_w,
                "mcs": mcs_w,
                "pricecharting": pc_w,
                "keepa": k_w,
            },
        },
        "reasoning_comment": reasoning.get("comment", ""),
    }

    logger.info(f"✅ Final valuation complete: ${result['final_price']:.2f}")
    return {**state, "valuation": result, "current_item": current_item}
