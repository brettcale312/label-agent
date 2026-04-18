"""
models.py
---------
Pydantic schemas for card-pricer.
"""

from pydantic import BaseModel
from typing import Optional


class CardVisionResult(BaseModel):
    """Raw output from the vision step."""
    title: str = ""
    set_name: str = ""
    card_number: str = ""
    rarity: str = ""
    condition: str = ""
    publisher_brand: str = ""
    year: str = ""
    bullet_1: str = ""
    bullet_2: str = ""
    bullet_3: str = ""
    # Claude's own knowledge-based price estimate (raw market value, pre-markup)
    ai_price_low: Optional[float] = None
    ai_price_high: Optional[float] = None
    ai_price_confidence: str = "low"   # "high" | "medium" | "low"
    # Claude's recommended search string for PriceCharting / eBay
    search_query: str = ""
    # Fan art / custom card detection
    is_fan_art: bool = False


# Google Sheets column order for cards (matches existing Apps Script)
CARD_COLUMNS = [
    "Title",
    "Bullet 1",
    "Bullet 2",
    "Price Source",
    "Price",
    "Inventory #",
    "Barcode",
    "Condition",
    "Base_Price",
    "AI Notes",
]
