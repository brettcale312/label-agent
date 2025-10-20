"""
valuation_logic.py
------------------
Applies heuristic pricing logic to Discogs and eBay data to produce
context-aware estimated values for records, comics, cards, etc.
"""

import math
from utils.logger import get_logger

logger = get_logger("valuation_logic")


def round_retail(price: float, venue: str = "antique_store") -> float:
    """Round to appropriate retail pricing based on venue."""
    if price <= 0:
        return 0
    
    if venue == "antique_store":
        # Antique store rounding: round numbers preferred
        if price < 3:
            return math.ceil(price * 4) / 4
        elif price < 5:
            return math.ceil(price * 2) / 2
        else:
            return math.ceil(price)
    else:
        return math.ceil(price) - 0.05 if price > 5 else round(price, 2)


def generate_condition_pricing_summary(discogs_data: dict, ebay_data: dict, item_meta: dict) -> str:
    """Generate a pricing summary showing prices for different conditions."""
    base_price = ebay_data.get("median_active_price") or discogs_data.get("median_price") or 5
    venue = item_meta.get("venue", "antique_store")
    
    conditions = {
        "records": ["sealed", "mint", "vg+", "vg", "good", "fair"],
        "comics": ["mint", "near mint", "very fine", "fine", "very good", "good"],
        "cards": ["mint", "near mint", "lightly played", "moderately played", "heavily played", "damaged"]
    }
    
    item_type = "records"
    if "card" in item_meta.get("category", "").lower():
        item_type = "cards"
    elif "comic" in item_meta.get("category", "").lower():
        item_type = "comics"
    
    condition_list = conditions.get(item_type, conditions["records"])
    pricing_summary = []
    for condition in condition_list:
        adjusted_price = apply_condition_multiplier(base_price, condition, category=item_type)
        
        if venue == "antique_store":
            if base_price < 5:
                final_price = adjusted_price * 2.5
            elif base_price < 10:
                final_price = adjusted_price * 1.75
            else:
                final_price = adjusted_price * 1.2
        else:
            final_price = adjusted_price
            
        final_price = round_retail(final_price, venue)
        pricing_summary.append(f"{condition}: ${final_price:.2f}")
    
    return "Pricing by condition: " + ", ".join(pricing_summary)


def calculate_comic_price(base_price: float, condition: str, year: int = None) -> float:
    """Calculate comic price using age-based multipliers and condition adjustments."""
    if not year:
        year = 2010
    
    if year > 2005:
        if base_price <= 5:
            base_multiplier = 1.75
        elif base_price <= 8:
            base_multiplier = 1.75 - (base_price - 5) * (0.65 / 3)
        else:
            base_multiplier = 1.1
    elif year >= 1980:
        base_multiplier = 2.0
    else:
        base_multiplier = 2.5
    
    adjusted_price = base_price * base_multiplier
    condition_lower = condition.lower()
    if "near mint" in condition_lower:
        adjusted_price *= 1.1
    elif "slabbed" in condition_lower:
        adjusted_price *= 1.2
    elif "very fine" in condition_lower:
        adjusted_price *= 1.0
    elif "fine" in condition_lower:
        adjusted_price *= 0.9
    elif "very good" in condition_lower:
        adjusted_price *= 0.8
    elif "good" in condition_lower:
        adjusted_price *= 0.7
    elif "fair" in condition_lower:
        adjusted_price *= 0.6
    
    return round_retail(adjusted_price, "antique_store")


def calculate_card_price(base_price: float, condition: str, rarity: str = None, year: int = None, venue: str = "antique_store") -> float:
    """
    Calculate card price (Pokémon, MTG, etc.) using rarity, era, and condition logic.
    """
    if not year:
        year = 2020  # assume modern era
    if not rarity:
        rarity = "★"  # assume rare if unknown

    # --- Step 1: Establish rarity base ---
    if "holo" in rarity.lower():
        rarity_base = 2.0
    elif rarity == "★":
        rarity_base = 1.0 if year >= 2016 else 2.0
    elif rarity == "◆":
        rarity_base = 0.75 if year >= 2016 else 1.25
    else:
        rarity_base = 0.5 if year >= 2016 else 1.0

    # --- Step 2: Use eBay/base price if meaningful ---
    if base_price <= 0:
        base_price = rarity_base

    # --- Step 3: Apply soft multiplier to avoid overpricing cheap cards ---
    if base_price < 3:
        adjusted_price = max(base_price, min(rarity_base * 1.25, 2.0))
    elif base_price < 5:
        adjusted_price = base_price * 1.1
    else:
        adjusted_price = base_price

    # --- Step 4: Apply condition multiplier (cards only) ---
    adjusted_price = apply_condition_multiplier(adjusted_price, condition, category="cards")

    # --- Step 5: Apply era bump for older cards ---
    if year < 2005:
        adjusted_price *= 1.4  # vintage bump
    elif year < 2012:
        adjusted_price *= 1.2  # mid-era bump

    # --- Step 6: Venue rounding ---
    final_price = round_retail(adjusted_price, venue)

    return final_price


def apply_condition_multiplier(base: float, condition: str, category: str = None) -> float:
    """
    Apply condition multipliers, but only significant for cards.
    Comics and records use their own logic in their respective pricing functions.
    """
    condition = (condition or "").strip().lower()
    multiplier = 1.0

    # Only apply to cards
    if category and "card" in category.lower():
        if "heavily played" in condition:
            multiplier = 0.8
        elif "damaged" in condition:
            multiplier = 0.5
        else:
            multiplier = 1.0

    adjusted = base * multiplier
    logger.info(f"[Condition] {category or 'general'} | {condition} → x{multiplier} → {adjusted:.2f}")
    return adjusted


def estimate_value(discogs_data: dict, ebay_data: dict, item_meta: dict) -> dict:
    """Estimate record/media value using combined Discogs/eBay data."""
    discogs_median = discogs_data.get("median_price") or 0
    ebay_median = ebay_data.get("median_active_price") or 0
    ebay_avg = ebay_data.get("avg_active_price") or 0
    num_for_sale = discogs_data.get("num_for_sale", 0)

    condition = item_meta.get("condition", "vg")
    venue = item_meta.get("venue", "online").lower()

    base_price = ebay_median if ebay_median > 0 else discogs_median
    if base_price == 0:
        base_price = (ebay_avg or discogs_median or 5)

    adj_price = apply_condition_multiplier(base_price, condition, category=item_meta.get("category"))

    if num_for_sale == 0:
        adj_price *= 1.3

    if venue == "antique_store":
        if base_price < 5:
            adj_price *= 2.5
        elif base_price < 10:
            adj_price *= 1.75
        else:
            adj_price *= 1.2
    elif venue == "ebay":
        adj_price *= 1.0
    elif venue == "record_show":
        adj_price *= 1.3

    final_price = round_retail(adj_price, venue)

    reasoning = []
    reasoning.append(f"Base price derived from {'eBay' if ebay_median else 'Discogs'} median.")
    if num_for_sale == 0:
        reasoning.append("No active Discogs listings -> scarcity bump.")
    if "sealed" in condition:
        reasoning.append("Condition sealed -> +60%.")
    if venue == "antique_store":
        reasoning.append("Antique store retail adjustment applied.")
    
    pricing_summary = generate_condition_pricing_summary(discogs_data, ebay_data, item_meta)
    reasoning.append(pricing_summary)

    return {
        "title": item_meta.get("title"),
        "venue": venue,
        "condition": condition,
        "discogs_median": discogs_median,
        "ebay_median": ebay_median,
        "estimated_price": final_price,
        "reasoning": "; ".join(reasoning)
    }
