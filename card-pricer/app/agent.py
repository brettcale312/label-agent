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
from .valuation import compute_price, apply_booth_rounding
from .database import get_next_inv_number
from .config import (
    ENABLE_MARKET_PRICING, AI_PROVIDER,
    ENABLE_GENERALIST_MODE, ENABLE_RANGE_PRICING, DEFAULT_CATEGORY,
)

FAN_ART_BULLET = "Custom/Fan Art - Not Official Pokemon TCG Product"

logger = logging.getLogger("agent")


TITLE_MAX  = 60
BULLET_MAX = 50


def _build_full_title(vision, is_card: bool = True) -> str:
    """
    Combine card name + set + number into a single display title.
    If the result exceeds TITLE_MAX chars, shorten the card-name portion
    (set_name and card_number are kept exact since they're used for search).

    For non-card categories, the title from the antique prompt is already a
    complete display string — just trim to TITLE_MAX.
    """
    card_name = vision.title or ("Unknown Card" if is_card else "Unknown Item")

    if not is_card:
        if len(card_name) <= TITLE_MAX:
            return card_name
        return card_name[:TITLE_MAX - 1].rstrip() + "…"

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


async def run_agent(
    image_bytes_list: list[bytes],
    batch_notes: str = "",
    category: str = "",
    upc: Optional[str] = None,
) -> dict:
    """
    Run the full pipeline on one or more item images.
    batch_notes — optional context from the batch (e.g. "Pokemon fan art cards").
    category   — "card" (default) or a non-card category when ENABLE_GENERALIST_MODE=true.
    Returns a dict of all session fields.
    """

    # Resolve effective category. When generalist mode is off, everything is
    # treated as a card regardless of what the caller passed in.
    effective_category = (category or DEFAULT_CATEGORY).lower()
    if not ENABLE_GENERALIST_MODE:
        effective_category = "card"
    is_card = effective_category == "card"

    # ── Step 1: Vision ────────────────────────────────────────────────────────
    logger.info(f"[agent] Step 1: Vision analysis (category={effective_category})")
    vision = await analyze_card(image_bytes_list, batch_notes=batch_notes, category=effective_category)
    logger.info(f"[agent] Identified: {vision.title!r} | set={vision.set_name!r} | fan_art={vision.is_fan_art}")

    # ── Step 2: Market pricing ────────────────────────────────────────────────
    # Cards: PriceCharting + eBay text search.
    # Non-cards with UPC: eBay GTIN lookup (PriceCharting skipped).
    # Non-cards without UPC: skip market pricing entirely.
    market_skipped = False
    if not ENABLE_MARKET_PRICING:
        logger.info("[agent] Market pricing disabled (ENABLE_MARKET_PRICING=false) — using AI estimate only")
        pc_median, ebay_median = None, None
        market_skipped = True
    elif vision.is_fan_art:
        logger.info("[agent] Fan art detected — skipping market pricing, using AI estimate only")
        pc_median, ebay_median = None, None
        market_skipped = True
    elif not is_card and not upc:
        logger.info("[agent] Non-card with no UPC — skipping market pricing")
        pc_median, ebay_median = None, None
        market_skipped = True
    else:
        logger.info(f"[agent] Step 2: Market pricing (upc={upc!r})")
        pc_median, ebay_median = await fetch_market_prices(
            vision.search_query or vision.title,
            upc=upc,
        )

    # ── Step 3: Valuation ─────────────────────────────────────────────────────
    # Range-pricing bypass: for non-card items when ENABLE_RANGE_PRICING=true,
    # leave final_price null so the user sets it from the suggested range.
    range_pricing_active = (not is_card) and ENABLE_RANGE_PRICING
    if range_pricing_active:
        logger.info("[agent] Range pricing active — computing midpoint from AI range")
        low = vision.ai_price_low
        high = vision.ai_price_high
        midpoint = (low + high) / 2 if (low and high) else (low or high or 1.0)
        final_price = apply_booth_rounding(midpoint)
        base_price = round(midpoint, 2)
        if low is not None and high is not None:
            price_source = f"AI estimate ${low:.2f}–${high:.2f} — midpoint ${final_price:.2f}"
        else:
            price_source = f"AI estimate — midpoint ${final_price:.2f}"
    else:
        logger.info("[agent] Step 3: Valuation")
        base_price, final_price, price_source = compute_price(
            pc_median=pc_median,
            ebay_median=ebay_median,
            ai_price_low=vision.ai_price_low,
            ai_price_high=vision.ai_price_high,
            condition=vision.condition,
        )

    # ── Build output ──────────────────────────────────────────────────────────
    full_title = _build_full_title(vision, is_card=is_card)
    ai_notes = _build_ai_notes(vision, pc_median, ebay_median, market_skipped=market_skipped)

    # Fan art: override bullet_2 automatically (cards only)
    bullet_2 = vision.bullet_2
    if is_card and vision.is_fan_art:
        bullet_2 = FAN_ART_BULLET
        if not ai_notes.endswith("."):
            ai_notes += " | Fan art detected — bullet 2 auto-set."
        logger.info(f"[agent] Fan art detected — bullet 2 set to standard disclaimer")

    # Assign inventory number from local DB sequence
    inventory_number = get_next_inv_number()

    # For non-card items, the "maker" field from the vision result is the primary
    # brand/publisher signal. Fall back to publisher_brand if the prompt returned it there.
    effective_publisher = vision.publisher_brand or vision.maker

    result = {
        # Identity
        "title": full_title,
        "display_title": full_title,
        "card_name": vision.title,
        "set_name": vision.set_name,
        "card_number": vision.card_number,
        "rarity": vision.rarity,
        "condition": vision.condition,
        "publisher_brand": effective_publisher,
        "year": vision.year,
        # Generalist fields (empty for cards)
        "category": effective_category,
        "era": vision.era,
        "maker": vision.maker or effective_publisher,
        "material": vision.material,
        "dimensions": vision.dimensions,
        # Label content — hard-capped at BULLET_MAX chars as safety net
        "bullet_1": _trim_bullet(vision.bullet_1),
        "bullet_2": _trim_bullet(bullet_2),
        "bullet_3": _trim_bullet(vision.bullet_3),
        # Pricing
        "price_source": price_source,
        "base_price": round(base_price, 2) if base_price else None,
        "price": final_price,
        "ai_price_low": vision.ai_price_low,
        "ai_price_high": vision.ai_price_high,
        "ai_price_confidence": vision.ai_price_confidence,
        "price_user_confirmed": 0,
        # Inventory assigned now; barcode filled after Sandpiper upload
        "inventory_number": inventory_number,
        "barcode": "",
        # Notes for review page
        "ai_notes": ai_notes,
        "is_fan_art": vision.is_fan_art,
        # Search query used for PriceCharting / eBay (useful for diagnosing unexpected prices)
        "search_query": vision.search_query,
        # UPC from barcode photo (if provided by user)
        "upc": upc,
    }

    final_str = f"${final_price:.2f}" if final_price is not None else "pending"
    logger.info(
        f"[agent] Done — {full_title!r} | base=${base_price:.2f} | final={final_str}"
    )
    return result
