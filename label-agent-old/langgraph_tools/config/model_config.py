"""
model_config.py
---------------
Enhanced with Explain Node tuning.
"""

import os
from utils.logger import get_logger

logger = get_logger("model_config")

AGENT_MODE = os.getenv("AGENT_MODE", "fast").lower()

MODEL_CONFIG = {
    # 🟢 GOOD — Bulk automation
    "fast": {
        "vision": "gpt-5-mini",
        "market": "gpt-5-mini",
        "pricing": "gpt-5-mini",
        "explain": "gpt-5-mini",          # still mini
        "temperature": 0.2,
        "explain_temperature": 0.5,       # ✍️ more creativity
        "max_output_tokens": 2000,
        "explain_max_tokens": 6000,       # 🧾 allow longer summaries
    },

    # 🟡 BETTER — Balanced performance
    "balanced": {
        "vision": "gpt-5-mini",
        "market": "gpt-5-mini",
        "pricing": "gpt-5-mini",
        "explain": "gpt-5-mini",
        "temperature": 0.25,
        "explain_temperature": 0.6,
        "max_output_tokens": 4000,
        "explain_max_tokens": 8000,
    },

    # 🔴 BEST — Long, expressive reasoning
    "expert": {
        "vision": "gpt-5-mini",
        "market": "gpt-5-mini",
        "pricing": "gpt-5-mini",
        "explain": "gpt-5-mini",
        "temperature": 0.3,
        "explain_temperature": 0.65,
        "max_output_tokens": 6000,
        "explain_max_tokens": 10000,      # ~7,500 words if ever needed
    },
}

ACTIVE_MODE = MODEL_CONFIG.get(AGENT_MODE, MODEL_CONFIG["fast"])

logger.info(
    f"[ModelConfig] 🧠 AGENT_MODE={AGENT_MODE.upper()} | "
    f"Vision={ACTIVE_MODE['vision']} | "
    f"Pricing={ACTIVE_MODE['pricing']} | "
    f"ExplainTemp={ACTIVE_MODE['explain_temperature']} | "
    f"ExplainMax={ACTIVE_MODE['explain_max_tokens']}"
)
