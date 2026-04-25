"""
config.py
---------
Central configuration for the card-pricer app.
Change AI_PROVIDER here (or in .env) to swap between Anthropic and OpenAI
without touching any other file.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── AI Provider ───────────────────────────────────────────────────────────────
# Set to "anthropic", "openai", or "gemini"
AI_PROVIDER: str = os.getenv("AI_PROVIDER", "anthropic").lower()
ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

# ── Market Tools ──────────────────────────────────────────────────────────────
# Set ENABLE_MARKET_PRICING=false to skip PriceCharting/eBay and rely on AI only.
# Useful when comps are unreliable (wrong card matches) or you want pure AI pricing.
ENABLE_MARKET_PRICING: bool = os.getenv("ENABLE_MARKET_PRICING", "false").lower() == "true"

# Set ENABLE_MULTIPLIERS=true to apply condition + booth markup multipliers on top of
# the base price. When false, the AI midpoint is used directly (just rounding applied).
ENABLE_MULTIPLIERS: bool = os.getenv("ENABLE_MULTIPLIERS", "false").lower() == "true"
ENABLE_EBAY: bool = os.getenv("ENABLE_EBAY_TOOL", "true").lower() == "true"
ENABLE_PRICECHARTING: bool = bool(os.getenv("PRICECHARTING_API_KEY"))

# ── Generalist mode (Phase 1 of antique-mall-OS expansion) ───────────────────
# Master switch. When false, the app is a pure card pricer — all generalist
# behavior below short-circuits to the card flow regardless of the sub-flags.
# See SoftwareCompanyVision.pdf for the broader roadmap.
ENABLE_GENERALIST_MODE: bool = os.getenv("ENABLE_GENERALIST_MODE", "false").lower() == "true"

# Show a category picker on the capture page + batch-create modal.
ENABLE_CATEGORY_PICKER: bool = os.getenv("ENABLE_CATEGORY_PICKER", "false").lower() == "true"

# For non-card categories, skip auto-pricing and surface the AI low/high range;
# user sets final price manually. Cards always ignore this flag.
ENABLE_RANGE_PRICING: bool = os.getenv("ENABLE_RANGE_PRICING", "false").lower() == "true"

# Add a dedicated "maker's mark / signature" photo slot on capture.
ENABLE_MAKERS_MARK_SLOT: bool = os.getenv("ENABLE_MAKERS_MARK_SLOT", "false").lower() == "true"

# Add a UPC/barcode photo slot on capture. AI reads the digits; used for precise eBay lookup.
ENABLE_UPC_SLOT: bool = os.getenv("ENABLE_UPC_SLOT", "false").lower() == "true"

# Raise the client-side photo cap from the card-default of 3.
ENABLE_EXTRA_PHOTOS: bool = os.getenv("ENABLE_EXTRA_PHOTOS", "false").lower() == "true"
EXTRA_PHOTO_LIMIT: int = int(os.getenv("EXTRA_PHOTO_LIMIT", "6"))

# Restore the old mobile edit-on-site view (removed when desktop-first was adopted).
ENABLE_MOBILE_EDIT: bool = os.getenv("ENABLE_MOBILE_EDIT", "false").lower() == "true"

# Show a purchase cost field on capture + desktop grid; include cost in Sandpiper upload.
# Useful for estate-sale operators who want to track acquisition cost per item.
ENABLE_COST_FIELD: bool = os.getenv("ENABLE_COST_FIELD", "false").lower() == "true"

# Default category for items when the picker is off or a batch has no category.
DEFAULT_CATEGORY: str = os.getenv("DEFAULT_CATEGORY", "card").lower()

# Label format selection. "auto" = card→card_2x2, anything else → antique_4x3.
#   card_2x2     — existing trading-card format (2 bullets)
#   antique_4x3  — existing 4x3 antique/comic format (3 bullets)
LABEL_FORMAT: str = os.getenv("LABEL_FORMAT", "auto").lower()

# Known categories — freeform, but these are the picker defaults.
KNOWN_CATEGORIES: list[str] = [
    "card", "pottery", "glass", "comic", "furniture",
    "jewelry", "book", "toy", "record", "other",
]


# ── Server ────────────────────────────────────────────────────────────────────
LOCAL_IP: str = os.getenv("LOCAL_IP", "localhost")
PORT: int = int(os.getenv("PORT", "8001"))
IOS_SHORTCUT_NAME: str = os.getenv("IOS_SHORTCUT_NAME", "Card Pricer")

DEBUG_LOGS: bool = os.getenv("DEBUG_LOGS", "false").lower() == "true"
