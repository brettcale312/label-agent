"""
valuation_logic.py
------------------
Contains value-adjustment helpers such as artist premiums,
rarity bonuses, and condition markups.
"""

# ---------------------------------------------------------------------
# Artist Premium Multipliers
# ---------------------------------------------------------------------
# Key = lowercase last or tag name (use simple substring match)
# Value = price multiplier to apply when that artist's name appears
# in cover credits or attributes.
# ---------------------------------------------------------------------

ARTIST_PREMIUMS = {
    # 🏆 Legendary / Iconic (≈ +20–25%)
    "mcfarlane": 1.25,
    "ross": 1.20,
    "lee": 1.20,
    "miller": 1.20,
    "kirby": 1.25,
    "ditko": 1.25,
    "romita": 1.20,
    "adams": 1.20,

    # ⭐ Modern “A-List” Variant Artists (≈ +10–15%)
    "liefeld": 1.10,
    "campbell": 1.15,
    "hughes": 1.15,
    "artgerm": 1.10,
    "momoko": 1.10,
    "capullo": 1.10,
    "finch": 1.10,
    "crain": 1.10,
    "kirkham": 1.10,
    "mayhew": 1.10,
    "frison": 1.10,
    "young": 1.05,
    "delotto": 1.10,
    "granov": 1.10,
    "bermejo": 1.10,
    "alexander": 1.10,
    "morales": 1.10,
    "cheung": 1.10,
    "dodson": 1.10,
    "tan": 1.10,
    "sienkiewicz": 1.15,
    "fairbairn": 1.05,
}

# (You can add more logic functions here later, e.g. round_retail, apply_condition_markup, etc.)
