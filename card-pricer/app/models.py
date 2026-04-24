"""
models.py
---------
Pydantic schemas for card-pricer.
"""

from pydantic import BaseModel
from typing import Optional


class CardVisionResult(BaseModel):
    """Raw output from the vision step. Fields after `is_fan_art` are used only
    in generalist (non-card) mode and stay blank/None for card items."""
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
    # Generalist fields — populated by the antique prompt, empty for cards
    category: str = ""
    era: str = ""
    maker: str = ""
    material: str = ""
    dimensions: str = ""


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
