"""
vision_node.py
---------------
Advanced structured vision node for the LangGraph Pricing Agent.

This node mirrors the original `_vision_node()` logic from PricingAgent,
preserving the full expert prompt for comics, cards, and vinyl records.

It extracts structured metadata from an image via GPT-Vision,
builds a normalized `current_item` dict, and adds a category hint
for downstream market tool selection.
"""

import json
import re
from typing import Dict, Any
from langchain_core.messages import SystemMessage, AIMessage
from langchain_openai import ChatOpenAI
from utils.logger import get_logger

logger = get_logger("vision_node")


# ---------------------------------------------------------------------
# Vision Node
# ---------------------------------------------------------------------
async def vision_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Extract structured collectible metadata from an image input."""
    item_type = state.get("current_item", {}).get("type", "item")

    detailed_prompt = """
You are a professional collectibles grader and catalog specialist.
Examine the image carefully and extract **all visible structured details**.
Identify the collectible precisely — aim to distinguish between editions, variants, or printings.

Respond in structured JSON with the following fields:

{
  "item_type": "comic | trading_card | vinyl_record | toy | other",
  "title": "",
  "series": "",
  "issue_number": "",
  "legacy_number": "",
  "variant_type": "",
  "publisher_or_brand": "",
  "release_year": "",
  "barcode_or_isbn": "",
  "cover_artist_or_label": "",
  "notable_characters": "",
  "key_issue_details": "",
  "rarity_or_limited_info": "",
  "condition_estimate": "",
  "visual_notes": "",
  "raw_summary": ""
}

### Enhanced Comic-Specific Rules ###
- Detect and output "cover_artist_or_label" (e.g., Rob Liefeld, Alex Ross, J. Scott Campbell).
- Include any anniversary or event logos (e.g., 50 Years, Fall of X).
- If a barcode block is visible, extract its numeric code.
- Estimate release_year from indicia or barcode pattern.
- Note any visible creator signatures on the cover (e.g., “Liefeld”, “McFarlane”).
- Grade visible condition cues (spine wear, corner dents, gloss loss).

**For Trading Cards:**
- Include game/series name, card number, rarity, and edition (1st Edition, Unlimited, Promo).
- Note holofoil, reverse holo, or alternate art.

**For Vinyl Records:**
- Include artist, album, label, catalog number, pressing details.

**General Rules:**
- Include every visible printed code (barcode, catalog, LGY, etc.)
- Keep `raw_summary` to 2 sentences summarizing what you see.
"""

    model = ChatOpenAI(model="gpt-4o-mini", temperature=0.2)
    messages = [SystemMessage(content=detailed_prompt)] + state["messages"]

    try:
        response = await model.ainvoke(messages)
        text = getattr(response, "content", "").strip()

        # Extract JSON block from model output
        match = re.search(r"\{.*\}", text, re.DOTALL)
        vision_data = json.loads(match.group(0)) if match else {"raw_summary": text, "item_type": "unknown"}

        # Determine category hint
        category_hint = None
        itype = (vision_data.get("item_type") or "").lower()
        if itype in ("comic", "comics"):
            category_hint = "comic"
        elif itype in ("record", "vinyl", "album", "vinyl_record"):
            category_hint = "record"
        elif itype in ("trading_card", "card", "tcg"):
            category_hint = "card"

        current_item = {
            "type": item_type,
            "title": vision_data.get("title"),
            "issue_number": vision_data.get("issue_number"),
            "publisher": vision_data.get("publisher_or_brand"),
            "condition": vision_data.get("condition_estimate"),
            "attributes": [
                vision_data.get("variant_type"),
                vision_data.get("legacy_number"),
                vision_data.get("key_issue_details"),
                vision_data.get("cover_artist_or_label"),
            ],
            "vision_summary": vision_data.get("raw_summary"),
            "category_hint": category_hint,
        }

        logger.info(
            f"[VisionNode] ✅ {current_item.get('title')} | {current_item.get('condition')} | "
            f"Category hint: {category_hint or 'general'}"
        )

    except Exception as e:
        logger.exception(f"[VisionNode] ❌ Vision structured output failed: {e}")
        current_item = {"type": item_type, "vision_summary": str(e)}

    # Return updated agent state
    return {
        "messages": state["messages"] + [AIMessage(content=str(current_item))],
        "session_id": state["session_id"],
        "user_id": state["user_id"],
        "current_item": current_item,
    }
