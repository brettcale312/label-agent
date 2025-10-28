"""
valuation_node.py
-----------------
Deterministic valuation logic for the LangGraph Pricing Agent.

Consumes:
  • market_data (from reasoning_node)
  • reasoning (weights + comments)
  • current_item (condition, venue, category, etc.)

This version:
  ✅ Supports MyComicShop weighting for comics
  ✅ Uses Discogs only for records/vinyl
  ✅ Rebuilds market_data if LangGraph dropped it
  ✅ Applies Robyn’s booth rounding rules
  ✅ Returns full merged state (no data loss)
"""

from typing import Dict, Any
from utils.logger import get_logger

logger = get_logger("valuation_node")

import json


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
        # Round up to nearest $0.25
        quarters = value * 4
        rounded_up = (int(quarters) + (0 if quarters.is_integer() else 1)) / 4
        return round(rounded_up, 2)
    else:
        # Round up to next full dollar
        return float(int(value) + (0 if value.is_integer() else 1))


# ---------------------------------------------------------------------
# Valuation Node
# ---------------------------------------------------------------------
async def valuation_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Compute the final price using weighted medians and condition multipliers."""
    # -----------------------------------------------------------------
    # Ensure market_data is present (rebuild if lost)
    # -----------------------------------------------------------------
    if "market_data" not in state or not state.get("market_data"):
        logger.warning("[ValuationNode] ⚠️ market_data missing — reconstructing from tool_results")
        from langgraph_tools.nodes.reasoning_node import _safe_float
        tool_results = state.get("tool_results", {}) or {}
        market = {}
        for _, result in tool_results.items():
            if isinstance(result, dict) and "source" in result:
                src = result["source"].lower()
                market[src] = {
                    "median": _safe_float(result.get("median") or result.get("median_price")),
                    "average": _safe_float(result.get("average") or result.get("average_price")),
                    "sample_count": int(result.get("samples") or result.get("sample_count") or 0),
                }
        state["market_data"] = market

    market = state.get("market_data", {})
    logger.warning(f"[ValuationNode] Market data keys: {list(market.keys())}")

    reasoning = state.get("reasoning") or {}
    current_item = state.get("current_item") or {}
    item_type = current_item.get("type", "").lower()

    # -----------------------------------------------------------------
    # Extract price data per source
    # -----------------------------------------------------------------
    ebay = market.get("ebay") or {}
    discogs = market.get("discogs") or {}
    mcs = market.get("mycomicshop") or {}

    ebay_price = ebay.get("median") or ebay.get("average") or 0
    discogs_price = discogs.get("median") or discogs.get("average") or 0
    mcs_price = mcs.get("median") or mcs.get("average") or 0

    # -----------------------------------------------------------------
    # Pull reasoning weights (with defaults)
    # -----------------------------------------------------------------
    e_w = reasoning.get("ebay_weight", 0.7)
    d_w = reasoning.get("discogs_weight", 0.3)
    mcs_w = reasoning.get("mcs_weight", 0.0)

    # -----------------------------------------------------------------
    # Apply category rules to ignore irrelevant sources
    # -----------------------------------------------------------------
    if item_type == "comic":
        # Comics → eBay + MyComicShop only
        d_w = 0.0
        if mcs_price > 0:
            e_w, mcs_w = 0.7, 0.3
        else:
            e_w, mcs_w = 1.0, 0.0
    elif item_type in ("record", "vinyl"):
        # Records → eBay + Discogs
        mcs_w = 0.0
        if discogs_price > 0:
            e_w, d_w = 0.7, 0.3
        else:
            e_w, d_w = 1.0, 0.0
    else:
        # Everything else → eBay only
        e_w, d_w, mcs_w = 1.0, 0.0, 0.0

    # Normalize weights
    total = e_w + d_w + mcs_w
    if total == 0:
        e_w, d_w, mcs_w = 1.0, 0.0, 0.0
    else:
        e_w, d_w, mcs_w = e_w / total, d_w / total, mcs_w / total

    # -----------------------------------------------------------------
    # Compute weighted base price
    # -----------------------------------------------------------------
    base_price = (
        (ebay_price * e_w)
        + (discogs_price * d_w)
        + (mcs_price * mcs_w)
    )

    logger.info(
        f"🧮 Valuation start: "
        f"eBay={ebay_price} ({e_w*100:.0f}%), "
        f"Discogs={discogs_price} ({d_w*100:.0f}%), "
        f"MyComicShop={mcs_price} ({mcs_w*100:.0f}%) → base={base_price:.2f}"
    )

    # -----------------------------------------------------------------
    # Venue / condition multipliers
    # -----------------------------------------------------------------
    venue = (current_item.get("venue") or "").lower()
    condition = (current_item.get("condition") or "").lower()
    category = (current_item.get("category") or item_type).lower()

    if venue in ("antique_mall", "antique_store", "booth"):
        if base_price < 10:
            base_price *= 1.75
        elif base_price < 30:
            base_price *= 1.35
        else:
            base_price *= 1.2
    elif venue in ("online", "ebay", "etsy", "shopify"):
        base_price *= 1.05  # small bump for shipping margin

    # Category tweaks
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
    # Final rounding logic (Robyn's booth rule)
    # -----------------------------------------------------------------
    if base_price <= 0:
        base_price = 5.00  # failsafe minimum for unpriced items
    else:
        base_price = apply_booth_rounding(base_price)

    result = {
        "final_price": float(base_price),
        "source_summary": {
            "ebay_price": ebay_price,
            "discogs_price": discogs_price,
            "mcs_price": mcs_price,
            "weights": {"ebay": e_w, "discogs": d_w, "mcs": mcs_w},
        },
        "reasoning_comment": reasoning.get("comment", ""),
    }

    logger.info(f"✅ Final valuation complete: ${result['final_price']:.2f}")

    # ✅ Preserve full pipeline state
    return {
        **state,
        "valuation": result,
        "current_item": current_item,
    }
