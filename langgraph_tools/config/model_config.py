"""
model_config.py
----------------
Central configuration for model selection and runtime behavior.

Implements the "good / better / best" switch for your LangGraph Pricing Agent.

Usage:
    - Set AGENT_MODE in your .env file to control the entire agent.

Example:
    AGENT_MODE=fast       # 🟢 Good
    AGENT_MODE=balanced   # 🟡 Better
    AGENT_MODE=expert     # 🔴 Best
"""

import os
from utils.logger import get_logger

logger = get_logger("model_config")

# ---------------------------------------------------------------------
# Global Mode
# ---------------------------------------------------------------------
AGENT_MODE = os.getenv("AGENT_MODE", "fast").lower()

# ---------------------------------------------------------------------
# Tier Definitions
# ---------------------------------------------------------------------
MODEL_CONFIG = {
    # 🟢 GOOD — Fastest, cheapest for bulk use
    "fast": {
        "vision": "gpt-4o-mini",
        "market": "gpt-4o-mini",
        "pricing": "gpt-4o-mini",
        "temperature": 0.2,
        "max_output_tokens": 2000,
    },

    # 🟡 BETTER — Balanced performance & reasoning
    "balanced": {
        "vision": "gpt-4o",
        "market": "gpt-4o",
        "pricing": "gpt-4o",
        "temperature": 0.25,
        "max_output_tokens": 4000,
    },

    # 🔴 BEST — Deep reasoning, high accuracy, higher cost
    "expert": {
        "vision": "gpt-5",
        "market": "gpt-5",
        "pricing": "gpt-5",
        "temperature": 0.3,
        "max_output_tokens": 6000,
    },
}

# ---------------------------------------------------------------------
# Active Configuration
# ---------------------------------------------------------------------
ACTIVE_MODE = MODEL_CONFIG.get(AGENT_MODE, MODEL_CONFIG["fast"])
logger.info(f"[ModelConfig] 🧠 AGENT_MODE={AGENT_MODE.upper()} | Vision={ACTIVE_MODE['vision']} | Pricing={ACTIVE_MODE['pricing']}")
