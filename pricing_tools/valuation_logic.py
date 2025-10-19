"""
valuation_logic.py
------------------
Applies heuristic pricing logic to Discogs and eBay data to produce
context-aware estimated values for records, collectibles, etc.

Inputs:
    - discogs_data: dict from Discogs API (median_price, lowest_price, num_for_sale)
    - ebay_data: dict from eBay Browse API (median_active_price, avg_active_price)
    - item_meta: dict with user/agent metadata:
        {
          "title": "Chicago Transit Authority",
          "condition": "sealed",
          "category": "vinyl",
          "venue": "antique_store"
        }

Output:
    dict with calculated price tiers and reasoning.
"""

import math

def round_retail(price: float, venue: str = "antique_store") -> float:
    """Round to appropriate retail pricing based on venue."""
    if price <= 0:
        return 0
    
    if venue == "antique_store":
        # Antique store rounding: round numbers preferred
        if price < 3:
            # Round up to nearest .25
            return math.ceil(price * 4) / 4
        elif price < 5:
            # Round up to nearest .50
            return math.ceil(price * 2) / 2
        else:
            # Round up to next dollar
            return math.ceil(price)
    else:
        # Default rounding for other venues
        return math.ceil(price) - 0.05 if price > 5 else round(price, 2)


def generate_condition_pricing_summary(discogs_data: dict, ebay_data: dict, item_meta: dict) -> str:
    """Generate a pricing summary showing prices for different conditions."""
    base_price = ebay_data.get("median_active_price") or discogs_data.get("median_price") or 5
    venue = item_meta.get("venue", "antique_store")
    
    # Define condition sets for different item types
    conditions = {
        "records": ["sealed", "mint", "vg+", "vg", "good", "fair"],
        "comics": ["mint", "near mint", "very fine", "fine", "very good", "good"],
        "cards": ["mint", "near mint", "lightly played", "moderately played", "heavily played", "damaged"]
    }
    
    # Determine item type based on category or meta
    item_type = "records"  # default
    if "card" in item_meta.get("category", "").lower():
        item_type = "cards"
    elif "comic" in item_meta.get("category", "").lower():
        item_type = "comics"
    
    condition_list = conditions.get(item_type, conditions["records"])
    
    # Calculate prices for each condition
    pricing_summary = []
    for condition in condition_list:
        adjusted_price = apply_condition_multiplier(base_price, condition)
        
        # Apply venue multiplier based on BASE price, not adjusted price
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
    """
    Calculate comic price using age-based multipliers and condition adjustments.
    
    Args:
        base_price: eBay median price for near mint condition
        condition: Comic condition (near mint, very fine, fine, etc.)
        year: Publication year (optional, defaults to modern)
    
    Returns:
        Final calculated price
    """
    if not year:
        year = 2010  # Default to modern if no year provided
    
    # Step 2: Determine age category and base multiplier
    if year > 2005:
        age_category = "modern"
        # Dynamic multiplier based on eBay median to prevent over-inflation
        if base_price <= 5:
            base_multiplier = 1.75
        elif base_price <= 8:
            # Linearly reduce from 1.75 → 1.1 across $5–$8
            base_multiplier = 1.75 - (base_price - 5) * (0.65 / 3)
        else:
            base_multiplier = 1.1  # gentle boost for high medians
    elif year >= 1980:
        age_category = "copper_bronze"
        base_multiplier = 2.0
    else:
        age_category = "silver_golden"
        base_multiplier = 2.5
    
    # Step 3: Apply base multiplier
    adjusted_price = base_price * base_multiplier
    
    # Step 4: Apply condition adjustments
    condition_lower = condition.lower()
    if "near mint" in condition_lower:
        adjusted_price *= 1.1  # +10% for near mint
    elif "slabbed" in condition_lower:
        adjusted_price *= 1.2  # +20% for slabbed
    elif "very fine" in condition_lower:
        adjusted_price *= 1.0  # Base price for very fine
    elif "fine" in condition_lower:
        adjusted_price *= 0.9  # -10% for fine
    elif "very good" in condition_lower:
        adjusted_price *= 0.8  # -20% for very good
    elif "good" in condition_lower:
        adjusted_price *= 0.7  # -30% for good
    elif "fair" in condition_lower:
        adjusted_price *= 0.6  # -40% for fair
    
    # Step 5: Round to booth-friendly price
    final_price = round_retail(adjusted_price, "antique_store")
    
    return final_price


def apply_condition_multiplier(base: float, condition: str) -> float:
    condition = (condition or "").lower()
    
    # Record conditions
    if "sealed" in condition:
        return base * 1.6
    if "mint" in condition:
        return base * 1.6
    if "vg+" in condition:
        return base * 1.2
    if "vg" in condition:
        return base * 1.0
    if "good" in condition:
        return base * 0.7
    if "fair" in condition:
        return base * 0.5
    
    # Comic conditions
    if "near mint" in condition:
        return base * 1.4
    if "very fine" in condition:
        return base * 1.2
    if "fine" in condition:
        return base * 1.0
    if "very good" in condition:
        return base * 0.8
    
    # Card conditions
    if "lightly played" in condition:
        return base * 1.2
    if "moderately played" in condition:
        return base * 1.0
    if "heavily played" in condition:
        return base * 0.7
    if "damaged" in condition:
        return base * 0.5
    
    # Default fallback
    return base * 1.0


def estimate_value(discogs_data: dict, ebay_data: dict, item_meta: dict) -> dict:
    discogs_median = discogs_data.get("median_price") or 0
    ebay_median = ebay_data.get("median_active_price") or 0
    ebay_avg = ebay_data.get("avg_active_price") or 0
    num_for_sale = discogs_data.get("num_for_sale", 0)

    condition = item_meta.get("condition", "vg")
    venue = item_meta.get("venue", "online").lower()

    # === Base value logic ===
    # Prefer eBay median if available, else Discogs median.
    base_price = ebay_median if ebay_median > 0 else discogs_median
    if base_price == 0:
        base_price = (ebay_avg or discogs_median or 5)

    # Apply condition multiplier
    adj_price = apply_condition_multiplier(base_price, condition)

    # Apply scarcity adjustment
    if num_for_sale == 0:
        adj_price *= 1.3

    # Venue-specific multiplier
    if venue == "antique_store":
        # More conservative multiplier based on HumanAccurateLogic.md
        # Scaled multipliers for different price ranges
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

    # === Compose reasoning ===
    reasoning = []
    reasoning.append(f"Base price derived from {'eBay' if ebay_median else 'Discogs'} median.")
    if num_for_sale == 0:
        reasoning.append("No active Discogs listings -> scarcity bump.")
    if "sealed" in condition:
        reasoning.append("Condition sealed -> +60%.")
    if venue == "antique_store":
        reasoning.append("Antique store retail adjustment applied.")
    
    # Add condition pricing summary
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

"""
Example usage:
from valuation_logic import estimate_value

discogs_data = {
    "median_price": 1.62,
    "lowest_price": 1.0,
    "num_for_sale": 14
}

ebay_data = {
    "median_active_price": 28.0,
    "avg_active_price": 26.5
}

item_meta = {
    "title": "Chicago Transit Authority (1969)",
    "condition": "sealed",
    "venue": "antique_store"
}

result = estimate_value(discogs_data, ebay_data, item_meta)
print(result)

Example output:
{
  'title': 'Chicago Transit Authority (1969)',
  'venue': 'antique_store',
  'condition': 'sealed',
  'discogs_median': 1.62,
  'ebay_median': 28.0,
  'estimated_price': 29.95,
  'reasoning': 'Base price derived from eBay median; Condition sealed -> +60%; Antique store retail adjustment applied.'
}

"""