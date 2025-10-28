"""
utils/normalizers.py
--------------------
Utility helpers for cleaning AI-generated notes and extracting readable price sources.
"""

import re
import json
from typing import Any, Dict, List
from utils.logger import get_logger

logger = get_logger("normalizers")


# ---------------------------------------------------------------------
# CLEAN AI NOTES
# ---------------------------------------------------------------------
def clean_ai_notes(ai_notes_raw: Any) -> str:
    """Normalize AI Notes to a readable single-line string."""
    if ai_notes_raw is None:
        return ""

    # Handle structured data
    if isinstance(ai_notes_raw, (dict, list)):
        try:
            text = json.dumps(ai_notes_raw, ensure_ascii=False)
        except Exception:
            text = str(ai_notes_raw)
    else:
        text = str(ai_notes_raw)

    # Collapse excessive whitespace
    text = re.sub(r"\s+", " ", text).strip()

    # Truncate safely (avoid massive dumps)
    if len(text) > 1000:
        text = text[:1000] + "…"

    return text


# ---------------------------------------------------------------------
# PRICE SOURCE NORMALIZER
# ---------------------------------------------------------------------
def extract_price_sources(tool_results: Dict[str, Any]) -> str:
    """
    Extracts human-readable price source names from LangGraph tool_results.
    Handles both named keys (e.g., 'ebay', 'mycomicshop') and unnamed nodes ('toolu_1')
    by inspecting internal 'source' or 'name' fields in the values.
    """
    if not tool_results:
        logger.debug("[PriceSource] No tool_results found → default to eBay")
        return "eBay"

    readable: List[str] = []
    debug_map: Dict[str, str] = {}

    for raw_name, raw_value in tool_results.items():
        lname = raw_name.lower()
        match = None

        # 1️⃣ First: check key name
        if "ebay" in lname:
            match = "eBay"
        elif "discogs" in lname:
            match = "Discogs"
        elif "comic" in lname:
            match = "MyComicShop"
        elif "gocollect" in lname:
            match = "GoCollect"
        elif "tcg" in lname:
            match = "TCGPlayer"
        elif "toolu" in lname or "internal" in lname:
            # 2️⃣ Second: infer from value content
            if isinstance(raw_value, dict):
                src = (
                    str(raw_value.get("source"))
                    or str(raw_value.get("market"))
                    or str(raw_value.get("name"))
                    or ""
                ).lower()

                if "ebay" in src:
                    match = "eBay"
                elif "discogs" in src:
                    match = "Discogs"
                elif "comic" in src:
                    match = "MyComicShop"
                elif "gocollect" in src:
                    match = "GoCollect"
                elif "tcg" in src:
                    match = "TCGPlayer"
            else:
                match = None

        # 3️⃣ Fallback to name/titlecase
        if not match and "toolu" not in lname:
            match = raw_name.replace("_", " ").title()

        if match:
            readable.append(match)
            debug_map[raw_name] = match
        else:
            debug_map[raw_name] = "UNMATCHED"

    # Deduplicate while preserving order
    seen = set()
    ordered_unique = [x for x in readable if not (x in seen or seen.add(x))]

    final_str = ", ".join(ordered_unique) or "eBay"

    logger.info(f"[PriceSource] 🧩 Raw keys: {list(tool_results.keys())}")
    logger.info(f"[PriceSource] 🔍 Map: {debug_map}")
    logger.info(f"[PriceSource] ✅ Final: {final_str}")

    return final_str
