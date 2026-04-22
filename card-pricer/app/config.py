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

# ── Server ────────────────────────────────────────────────────────────────────
LOCAL_IP: str = os.getenv("LOCAL_IP", "localhost")
PORT: int = int(os.getenv("PORT", "8001"))
IOS_SHORTCUT_NAME: str = os.getenv("IOS_SHORTCUT_NAME", "Card Pricer")

DEBUG_LOGS: bool = os.getenv("DEBUG_LOGS", "false").lower() == "true"
