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
    Handles both named keys (e.g., 'search_ebay', 'search_pricecharting_tool')
    and unnamed nodes ('toolu_1') by inspecting internal fields.
    """

    if not tool_results:
        logger.debug("[PriceSource] No tool_results found → default to eBay")
        return "eBay"

    readable: List[str] = []
    debug_map: Dict[str, str] = {}

    # Known tool name mapping
    TOOL_MAP = {
        "search_ebay": "eBay",
        "search_mycomicshop": "MyComicShop",
        "search_discogs": "Discogs",
        "search_keepa_tool": "Keepa",
        "search_keepa_smart_tool": "Keepa",
        "search_pricecharting_tool": "PriceCharting",  # ✅ Added
        "search_gocollect_tool": "GoCollect",
        "search_heritage_tool": "Heritage",
        "smart_search": "SmartSearch",
    }

    for raw_name, raw_value in tool_results.items():
        lname = raw_name.lower()
        match = None

        # 1️⃣ Try direct map lookup
        for key, display in TOOL_MAP.items():
            if key in lname:
                match = display
                break

        # 2️⃣ If not matched, infer from value content
        if not match and isinstance(raw_value, dict):
            src = (
                str(raw_value.get("source"))
                or str(raw_value.get("market"))
                or str(raw_value.get("name"))
                or ""
            ).lower()
            for key, display in TOOL_MAP.items():
                if key.replace("search_", "").replace("_tool", "") in src:
                    match = display
                    break

        # 3️⃣ Fallback: title-case the raw key if nothing else
        if not match and "toolu" not in lname:
            match = raw_name.replace("_", " ").title()

        # 4️⃣ Validate that the result actually has numeric data
        if isinstance(raw_value, dict):
            median = raw_value.get("median") or raw_value.get("avg") or raw_value.get("mean") or 0
            try:
                numeric_val = float(median)
            except (TypeError, ValueError):
                numeric_val = 0
        else:
            numeric_val = 0

        if match and numeric_val > 0:
            readable.append(match)
            debug_map[raw_name] = match
        elif match:
            debug_map[raw_name] = f"{match} (no data)"
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
