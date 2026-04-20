"""
valuation.py
------------
Computes the final booth price from market data + Claude's knowledge estimate.

Weights adapt based on what data is actually available:
  - All three sources: PriceCharting 40%, eBay 20%, Claude 40%
  - PC + Claude only: 50/50
  - eBay + Claude only: eBay 40%, Claude 60%
  - Claude only: 100% (always present — this is the ChatGPT-equivalent baseline)

Then applies condition multiplier + booth markup + Robyn's rounding rules.

Adapted from label-agent/langgraph_tools/nodes/valuation_node.py
"""

import math
import logging
from typing import Optional

logger = logging.getLogger("valuation")


# ─────────────────────────────────────────────────────────────────────────────
# Booth rounding (Robyn's rules)
# ─────────────────────────────────────────────────────────────────────────────

def apply_booth_rounding(value: float) -> float:
    """
    < $1    → $1.00
    $1–$5   → round up to nearest quarter
    $5+     → round up to whole dollar
    """
    if value <= 0:
        return 0.0
    if value < 1:
        return 1.00
    if value < 5:
        quarters = value * 4
        return round(math.ceil(quarters) / 4, 2)
    return float(math.ceil(value))


# ─────────────────────────────────────────────────────────────────────────────
# Condition multipliers
# ─────────────────────────────────────────────────────────────────────────────

def _condition_multiplier(condition: str) -> float:
    c = condition.lower()
    if "mint" in c or "nm" in c:
        return 1.10
    if "poor" in c:
        return 0.60
    if "fair" in c or "gd" in c:
        return 0.85
    return 1.0  # Good/VG or unknown


# ─────────────────────────────────────────────────────────────────────────────
# Booth markup tiers (from existing valuation_node.py)
# ─────────────────────────────────────────────────────────────────────────────

def _booth_markup(base: float) -> float:
    if base < 10:
        return base * 1.75
    if base < 30:
        return base * 1.35
    return base * 1.20


# ─────────────────────────────────────────────────────────────────────────────
# Main compute function
# ─────────────────────────────────────────────────────────────────────────────

def compute_price(
    pc_median: Optional[float],
    ebay_median: Optional[float],
    ai_price_low: Optional[float],
    ai_price_high: Optional[float],
    condition: str,
) -> tuple[float, float, str]:
    """
    Returns (base_price, final_price, price_source_string).

    base_price  = weighted market average before markup (shown in review UI)
    final_price = booth-ready price after condition + markup + rounding
    price_source_string = human-readable description of what went into the price
    """

    # Claude's midpoint estimate
    claude_mid: Optional[float] = None
    if ai_price_low is not None and ai_price_high is not None:
        claude_mid = (ai_price_low + ai_price_high) / 2.0
    elif ai_price_low is not None:
        claude_mid = ai_price_low
    elif ai_price_high is not None:
        claude_mid = ai_price_high

    # ── Adaptive weighting ───────────────────────────────────────────────────
    source_parts = []
    base = 0.0

    if pc_median and ebay_median and claude_mid:
        base = pc_median * 0.40 + ebay_median * 0.20 + claude_mid * 0.40
        source_parts = [
            f"PriceCharting ${pc_median:.2f} (40%)",
            f"eBay ${ebay_median:.2f} (20%)",
            f"Claude ${claude_mid:.2f} (40%)",
        ]

    elif pc_median and claude_mid:
        base = pc_median * 0.50 + claude_mid * 0.50
        source_parts = [
            f"PriceCharting ${pc_median:.2f} (50%)",
            f"Claude ${claude_mid:.2f} (50%)",
        ]

    elif ebay_median and claude_mid:
        base = ebay_median * 0.40 + claude_mid * 0.60
        source_parts = [
            f"eBay ${ebay_median:.2f} (40%)",
            f"Claude ${claude_mid:.2f} (60%)",
        ]

    elif pc_median and ebay_median:
        base = pc_median * 0.60 + ebay_median * 0.40
        source_parts = [
            f"PriceCharting ${pc_median:.2f} (60%)",
            f"eBay ${ebay_median:.2f} (40%)",
        ]

    elif pc_median:
        base = pc_median
        source_parts = [f"PriceCharting ${pc_median:.2f}"]

    elif ebay_median:
        base = ebay_median
        source_parts = [f"eBay ${ebay_median:.2f}"]

    elif claude_mid:
        base = claude_mid
        source_parts = [f"Claude estimate ${claude_mid:.2f} (no market data found)"]

    else:
        base = 5.0
        source_parts = ["No data — defaulted to $5.00"]

    base_price = round(base, 2)

    # ── Condition multiplier ─────────────────────────────────────────────────
    base *= _condition_multiplier(condition)

    # ── Card category nudge (5%) ─────────────────────────────────────────────
    base *= 1.05

    # ── Booth markup ─────────────────────────────────────────────────────────
    base = _booth_markup(base)

    # ── Rounding ─────────────────────────────────────────────────────────────
    final_price = apply_booth_rounding(base)

    price_source = " + ".join(source_parts)

    logger.info(
        f"[valuation] base_price=${base_price:.2f} | condition={condition!r} "
        f"| final=${final_price:.2f} | sources: {price_source}"
    )

    return base_price, final_price, price_source
