"""
utils/pricing_rules.py
----------------------
Reusable heuristics for rounding and condition multipliers.
Simplified from legacy valuation_logic.py.
"""

import math

def round_retail(price: float, venue: str = "antique_store") -> float:
    """Round to appropriate retail pricing based on venue type."""
    if price <= 0:
        return 0
    if venue == "antique_store":
        if price < 3:
            return math.ceil(price * 4) / 4
        elif price < 5:
            return math.ceil(price * 2) / 2
        else:
            return math.ceil(price)
    # Online / marketplace style (.95 endings)
    return math.ceil(price) - 0.05 if price > 5 else round(price, 2)


#This wasn't quite right, but the idea might be useful later

# def apply_condition_multiplier(base: float, condition: str, category: str | None = None) -> float:
#     """Apply basic condition multipliers."""
#     condition = (condition or "").strip().lower()
#     multiplier = 1.0
#     if category and "comic" in category.lower():
#         scale = {
#             "near mint": 1.4, "very fine": 1.2, "fine": 1.0,
#             "very good": 0.8, "good": 0.7, "fair": 0.5
#         }
#         for k, v in scale.items():
#             if k in condition: multiplier = v
#     elif category and "card" in category.lower():
#         if "heavily played" in condition: multiplier = 0.8
#         elif "damaged" in condition: multiplier = 0.5
#     elif category and ("record" in category.lower() or "vinyl" in category.lower()):
#         scale = {"sealed": 1.6, "mint": 1.6, "vg+": 1.2, "vg": 1.0, "good": 0.7, "fair": 0.5}
#         for k, v in scale.items():
#             if k in condition: multiplier = v
#     return round(base * multiplier, 2)
