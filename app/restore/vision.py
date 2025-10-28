"""
vision_node.py
---------------
Vision node for LangGraph Pricing Agent.

✅ Extracts structured collectible details from an image
✅ Generates 3 short marketing bullets (antique booth or eBay use)
✅ Handles comics, cards, records, and general items
✅ Improves card fine-print recognition (number, rarity symbols, holo type)
✅ Improves record label, genre, and year extraction
✅ Builds display_string and search_string via format_rules
✅ Returns a normalized current_item ready for valuation and export
"""

import json
import base64
import re
from langchain_core.messages import HumanMessage
from utils.logger import get_logger
from langgraph_tools.context.base_context import get_llm_context
from app.models import row_order
from langgraph_tools.format_rules import build_display_and_search_strings

logger = get_logger("vision_node")


# ---------------------------------------------------------------------
# Vision Node
# ---------------------------------------------------------------------
async def vision_node(state):
    """Analyze the image and return structured details + sales bullets."""

    llm = get_llm_context()

    # --------------------------------------------------------------
    # Extract image bytes (from direct bytes or message structure)
    # --------------------------------------------------------------
    image_bytes = state.get("image_bytes")
    if not image_bytes:
        messages = state.get("messages", [])
        if messages and isinstance(messages[0].content, list):
            for part in messages[0].content:
                if part.get("type") == "image_url" and "data:image" in part["image_url"].get("url", ""):
                    try:
                        b64_data = part["image_url"]["url"].split(",")[1]
                        image_bytes = base64.b64decode(b64_data)
                        logger.debug("[VisionNode] ✅ Extracted image bytes from message content.")
                        break
                    except Exception as e:
                        logger.warning(f"[VisionNode] ⚠️ Failed to decode image from message: {e}")

    item_type = (state.get("item_type") or state.get("current_item", {}).get("type") or "anything").lower()
    if not image_bytes:
        logger.warning("[VisionNode] ⚠️ No image bytes in state.")
        return state

    # --------------------------------------------------------------
    # Build schema & prompt
    # --------------------------------------------------------------
    columns = row_order(item_type)
    schema_str = json.dumps(columns, indent=2)

    # Extended structured schema for the model to fill
    extended_schema = """
    {
      "item_type": "comic | card | record | toy | other",
      "title": "",
      "series": "",
      "issue_number": "",
      "variant_type": "",
      "publisher_or_brand": "",
      "release_year": "",
      "barcode_or_isbn": "",
      "cover_artist_or_label": "",
      "key_issue_details": "",
      "rarity_or_limited_info": "",
      "condition_estimate": "",
      "set_name": "",
      "card_number": "",
      "rarity_symbol": "",
      "holo_type": "",
      "artist_or_band": "",
      "genre": "",
      "material": "",
      "era": "",
      "raw_summary": "",
      "sales_bullets": [
        "Short marketing bullet 1",
        "Short marketing bullet 2",
        "Short marketing bullet 3"
      ]
    }
    """

    # Tailored extraction and bullet instructions
    if item_type == "comic":
        bullet_instruction = """
        Create exactly 3 short, catchy marketing bullets (1 line each)
        highlighting what makes this comic desirable to collectors or
        antique-shop buyers. Mention characters, cover art, story significance,
        or condition. Avoid long sentences, emojis, or hashtags.
        Focus on variant editions, first appearances, and visual features.
        """
    elif item_type == "card":
        bullet_instruction = """
        Create exactly 3 brief bullets (under 8 words each)
        suitable for a 2x2 label describing the card’s appeal.
        Mention rarity (Common, Rare, Ultra Rare, etc.), holo type, or set.
        Pay attention to fine print at the bottom for card number and rarity symbol.
        """
    elif item_type == "record":
        bullet_instruction = """
        Create exactly 3 short bullets for a vinyl record,
        focusing on artist, label, genre, or notable songs.
        Mention if it's a limited edition, colored vinyl, or reissue.
        """
    else:
        bullet_instruction = """
        Create exactly 3 short bullets describing appeal or condition
        for an antique booth shopper. Keep each under 10 words.
        Mention material, craftsmanship, or era if visible.
        """

    # Prompt assembly
    prompt = f"""
    You are a professional collectibles cataloging expert and marketing copywriter.
    Analyze the provided image of a {item_type} and return structured details.

    Respond ONLY with valid JSON matching this structure:
    {extended_schema}

    Notes:
    - Focus on visible identifiers (titles, numbers, rarity marks, or artist info).
    - For cards: look at the bottom edge for card number and rarity symbol.
      Convert rarity symbols to text if possible (● Common, ◆ Uncommon, ★ Rare).
    - For records: extract artist, album title, label, year, and genre.
    - For comics: extract title, issue number, variant edition, and publisher.
    - Grade condition using collector terms (e.g., Near Mint, Very Fine, Good).
    - Include a short "raw_summary" (1–2 sentences describing the image).
    - {bullet_instruction}
    - Ensure exactly 3 bullets are always provided.
    - Do not output anything outside the JSON object.
    """

    # --------------------------------------------------------------
    # Prepare model input
    # --------------------------------------------------------------
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    image_url = f"data:image/jpeg;base64,{image_b64}"

    message = HumanMessage(
        content=[
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": image_url}},
        ]
    )

    # --------------------------------------------------------------
    # LLM call with safe JSON extraction
    # --------------------------------------------------------------
    try:
        response = await llm.ainvoke([message])
        text = getattr(response, "content", str(response)).strip()
        json_blocks = re.findall(r"\{.*?\}", text, re.DOTALL)
        if not json_blocks:
            raise ValueError("No JSON detected in model output.")
        json_text = max(json_blocks, key=len)
        vision_data = json.loads(json_text)
        logger.info("[VisionNode DEBUG] Raw vision_data: %s", json.dumps(vision_data, indent=2))
    except Exception as e:
        logger.warning(f"[VisionNode] ⚠️ JSON parse failed: {e}")
        vision_data = {"AI Notes": f"Vision extraction error: {e}", "sales_bullets": ["", "", ""]}

    # --------------------------------------------------------------
    # Normalize and map results
    # --------------------------------------------------------------
    title = vision_data.get("title") or "Untitled"
    issue_number = vision_data.get("issue_number") or ""
    publisher = vision_data.get("publisher_or_brand") or "Unknown"
    condition = vision_data.get("condition_estimate") or "Unspecified"
    barcode = vision_data.get("barcode_or_isbn") or ""
    variant = vision_data.get("variant_type") or ""
    rarity = vision_data.get("rarity_or_limited_info") or vision_data.get("rarity_symbol") or ""
    set_name = vision_data.get("set_name") or ""
    card_number = vision_data.get("card_number") or ""
    holo_type = vision_data.get("holo_type") or ""
    artist = vision_data.get("artist_or_band") or vision_data.get("cover_artist_or_label") or ""
    genre = vision_data.get("genre") or ""
    bullets = vision_data.get("sales_bullets") or ["", "", ""]

    # Pad / trim bullets to exactly 3
    while len(bullets) < 3:
        bullets.append("")
    if len(bullets) > 3:
        bullets = bullets[:3]

    # --------------------------------------------------------------
    # Build normalized current_item
    # --------------------------------------------------------------
    current_item = {
        "type": item_type,
        "title": title,
        "issue_number": issue_number,
        "publisher": publisher,
        "variant": variant,
        "barcode": barcode,
        "condition": condition,
        "set_name": set_name,
        "card_number": card_number,
        "rarity": rarity,
        "holo_type": holo_type,
        "artist": artist,
        "genre": genre,
        "bullet1": bullets[0],
        "bullet2": bullets[1],
        "bullet3": bullets[2],
        "vision_summary": vision_data.get("raw_summary") or "",
        "category_hint": item_type,
        "vision_fields": vision_data,
    }

    # --------------------------------------------------------------
    # Build standardized display & search strings
    # --------------------------------------------------------------
    current_item = build_display_and_search_strings(current_item)

    logger.info(
        f"[VisionNode] ✅ {current_item.get('display_string')} | "
        f"{publisher or 'Unknown'} | {condition or 'Unspecified'} | "
        f"Bullets: {bullets}"
    )

    return {
        **state,
        "current_item": current_item,
        "messages": state.get("messages", []),
    }
