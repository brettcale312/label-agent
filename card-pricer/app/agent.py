"""
agent.py
--------
Orchestrates the three-step card pricing pipeline:

  1. vision.py  — Claude identifies card, generates bullets, estimates price
  2. pricing.py — PriceCharting + eBay run concurrently (optional, may return None)
  3. valuation.py — Adaptive weighted price + booth rounding

Returns a flat dict ready to be saved as a session JSON file.
"""

import logging
from typing import Optional

from .vision import analyze_card
from .pricing import fetch_market_prices
from .valuation import compute_price
from .database import get_next_inv_number
from .config import ENABLE_MARKET_PRICING, AI_PROVIDER

FAN_ART_BULLET = "Custom/Fan Art - Not Official Pokemon TCG Product"

logger = logging.getLogger("agent")


TITLE_MAX  = 60
BULLET_MAX = 50


def _build_full_title(vision) -> str:
    """
    Combine card name + set + number into a single display title.
    If the result exceeds TITLE_MAX chars, shorten the card-name portion
    (set_name and card_number are kept exact since they're used for search).
    """
    card_name = vision.title or "Unknown Card"
    parts = []
    if vision.set_name:
        parts.append(vision.set_name)
    if vision.card_number:
        parts.append(f"#{vision.card_number}")

    suffix = f" ({' '.join(parts)})" if parts else ""
    full   = f"{card_name}{suffix}"

    if len(full) <= TITLE_MAX:
        return full

    # Trim the card-name portion to make room for the suffix
    allowed = TITLE_MAX - len(suffix) - 1   # -1 for the ellipsis
    if allowed < 4:
        # Suffix alone is nearly at the limit — just truncate the whole thing
        return full[:TITLE_MAX]
    shortened = card_name[:allowed].rstrip() + "…"
    logger.debug(f"[agent] Title trimmed: {full!r} → {shortened + suffix!r}")
    return shortened + suffix


def _trim_bullet(text: str) -> str:
    """Hard-cap a bullet at BULLET_MAX characters with ellipsis."""
    if not text or len(text) <= BULLET_MAX:
        return text
    trimmed = text[:BULLET_MAX - 1].rstrip() + "…"
    logger.debug(f"[agent] Bullet trimmed: {text!r} → {trimmed!r}")
    return trimmed


def _build_ai_notes(vision, pc_median: Optional[float], ebay_median: Optional[float], market_skipped: bool = False) -> str:
    """Generate a brief AI notes string for the review page."""
    lines = []

    if AI_PROVIDER == "openai":
        model_label = "ChatGPT estimate"
    elif AI_PROVIDER == "gemini":
        model_label = "Gemini estimate"
    else:
        model_label = "Claude estimate"
    conf = vision.ai_price_confidence or "low"
    if vision.ai_price_low and vision.ai_price_high:
        lines.append(
            f"{model_label}: ${vision.ai_price_low:.2f}–${vision.ai_price_high:.2f} "
            f"({conf} confidence)"
        )
    elif vision.ai_price_low:
        lines.append(f"{model_label}: ~${vision.ai_price_low:.2f} ({conf} confidence)")

    if market_skipped:
        lines.append("Market comps disabled — AI pricing only")
    else:
        if pc_median:
            lines.append(f"PriceCharting: ${pc_median:.2f}")
        else:
            lines.append("PriceCharting: no match")

        if ebay_median:
            lines.append(f"eBay median: ${ebay_median:.2f}")
        else:
            lines.append("eBay: no match")

    if vision.rarity:
        lines.append(f"Rarity: {vision.rarity}")

    return " | ".join(lines)


async def run_agent(image_bytes_list: list[bytes], batch_notes: str = "") -> dict:
    """
    Run the full pipeline on one or more card images.
    batch_notes — optional context from the batch (e.g. "Pokemon fan art cards").
    Returns a dict of all session fields (ready to save as JSON).
    """

    # ── Step 1: Vision ────────────────────────────────────────────────────────
    logger.info("[agent] Step 1: Vision analysis")
    vision = await analyze_card(image_bytes_list, batch_notes=batch_notes)
    logger.info(f"[agent] Identified: {vision.title!r} | set={vision.set_name!r} | fan_art={vision.is_fan_art}")

    # ── Step 2: Market pricing ────────────────────────────────────────────────
    market_skipped = False
    if not ENABLE_MARKET_PRICING:
        logger.info("[agent] Market pricing disabled (ENABLE_MARKET_PRICING=false) — using AI estimate only")
        pc_median, ebay_median = None, None
        market_skipped = True
    elif vision.is_fan_art:
        # Fan art has no reliable set/number to search — skip market tools entirely
        logger.info("[agent] Fan art detected — skipping market pricing, using AI estimate only")
        pc_median, ebay_median = None, None
        market_skipped = True
    else:
        logger.info("[agent] Step 2: Market pricing")
        pc_median, ebay_median = await fetch_market_prices(vision.search_query or vision.title)

    # ── Step 3: Valuation ─────────────────────────────────────────────────────
    logger.info("[agent] Step 3: Valuation")
    base_price, final_price, price_source = compute_price(
        pc_median=pc_median,
        ebay_median=ebay_median,
        ai_price_low=vision.ai_price_low,
        ai_price_high=vision.ai_price_high,
        condition=vision.condition,
    )

    # ── Build output ──────────────────────────────────────────────────────────
    full_title = _build_full_title(vision)
    ai_notes = _build_ai_notes(vision, pc_median, ebay_median, market_skipped=market_skipped)

    # Fan art: override bullet_2 automatically
    bullet_2 = vision.bullet_2
    if vision.is_fan_art:
        bullet_2 = FAN_ART_BULLET
        if not ai_notes.endswith("."):
            ai_notes += " | Fan art detected — bullet 2 auto-set."
        logger.info(f"[agent] Fan art detected — bullet 2 set to standard disclaimer")

    # Assign inventory number from local DB sequence
    inventory_number = get_next_inv_number()

    result = {
        # Identity
        "title": full_title,
        "display_title": full_title,
        "card_name": vision.title,
        "set_name": vision.set_name,
        "card_number": vision.card_number,
        "rarity": vision.rarity,
        "condition": vision.condition,
        "publisher_brand": vision.publisher_brand,
        "year": vision.year,
        # Label content — hard-capped at BULLET_MAX chars as safety net
        "bullet_1": _trim_bullet(vision.bullet_1),
        "bullet_2": _trim_bullet(bullet_2),
        "bullet_3": _trim_bullet(vision.bullet_3),
        # Pricing
        "price_source": price_source,
        "base_price": round(base_price, 2),
        "price": final_price,
        # Inventory assigned now; barcode filled after Sandpiper upload
        "inventory_number": inventory_number,
        "barcode": "",
        # Notes for review page
        "ai_notes": ai_notes,
        "is_fan_art": vision.is_fan_art,
        # Search query used for PriceCharting / eBay (useful for diagnosing unexpected prices)
        "search_query": vision.search_query,
    }

    logger.info(
        f"[agent] Done — {full_title!r} | base=${base_price:.2f} | final=${final_price:.2f}"
    )
    return result
