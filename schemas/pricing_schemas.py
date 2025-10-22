"""
Unified schema definitions for structured pricing outputs.
These are used by LangGraph prompts, FastAPI output alignment, and Google Sheets.
"""

from typing import Dict, Any

# --- Comic Books ---
COMIC_SCHEMA: Dict[str, Any] = {
    "Title_Issue": "",
    "Bullet 1": "",
    "Bullet 2": "",
    "Bullet 3": "",
    "Publisher": "",
    "Base_Price": "",
    "Condition": "",
    "Price": "",
    "Inventory #": "",
    "Barcode": "",
    "AI Notes": ""
}

# --- Trading Cards ---
CARD_SCHEMA: Dict[str, Any] = {
    "Title": "",
    "Bullet 1": "",
    "Bullet 2": "",
    "Set": "",
    "Number": "",
    "Rarity": "",
    "Price_Source": "",
    "Base_Price": "",
    "Condition": "",
    "Price": "",
    "Inventory #": "",
    "Barcode": "",
    "AI Notes": ""
}

# --- Vinyl Records ---
RECORD_SCHEMA: Dict[str, Any] = {
    "Title": "",
    "Artist": "",
    "Label": "",
    "Year": "",
    "Genre": "",
    "Base_Price": "",
    "Condition": "",
    "Price": "",
    "Inventory #": "",
    "Barcode": "",
    "AI Notes": ""
}

# --- Generic / “Anything Else” ---
ANYTHING_SCHEMA: Dict[str, Any] = {
    "Title": "",
    "Category": "",
    "Description": "",
    "Material": "",
    "Era": "",
    "Base_Price": "",
    "Condition": "",
    "Price": "",
    "Inventory #": "",
    "Barcode": "",
    "AI Notes": ""
}

# --- Map for easy reference ---
SCHEMA_MAP = {
    "comic": COMIC_SCHEMA,
    "card": CARD_SCHEMA,
    "record": RECORD_SCHEMA,
    "anything": ANYTHING_SCHEMA
}


def get_schema(item_type: str) -> Dict[str, Any]:
    """Retrieve the structured schema for a given item type."""
    return SCHEMA_MAP.get(item_type.lower(), ANYTHING_SCHEMA)
