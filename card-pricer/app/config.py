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
# Set to "anthropic" or "openai"
AI_PROVIDER: str = os.getenv("AI_PROVIDER", "anthropic").lower()
ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# ── Market Tools ──────────────────────────────────────────────────────────────
ENABLE_EBAY: bool = os.getenv("ENABLE_EBAY_TOOL", "true").lower() == "true"
ENABLE_PRICECHARTING: bool = bool(os.getenv("PRICECHARTING_API_KEY"))

# ── Server ────────────────────────────────────────────────────────────────────
LOCAL_IP: str = os.getenv("LOCAL_IP", "localhost")
PORT: int = int(os.getenv("PORT", "8001"))
IOS_SHORTCUT_NAME: str = os.getenv("IOS_SHORTCUT_NAME", "Card Pricer")

DEBUG_LOGS: bool = os.getenv("DEBUG_LOGS", "false").lower() == "true"
