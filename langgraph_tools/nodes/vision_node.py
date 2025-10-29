"""
vision_node.py
---------------
Vision node for LangGraph Pricing Agent.

✅ Uses GPT-5-Vision only for image OCR / structured extraction
✅ Keeps other nodes on AGENT_MODE (fast, balanced, expert)
✅ Adds regex + heuristic fallbacks for issue numbers, variants, and publisher
✅ Generates 3 short marketing bullets (antique booth or eBay use)
✅ Builds display_string and search_string via format_rules
"""

import json
import base64
import re
from langchain_core.messages import HumanMessage
from utils.logger import get_logger
from langgraph_tools.context.base_context import get_llm_context
from app.models import row_order
from langgraph_tools.format_rules import build_display_and_search_strings
from openai import AsyncOpenAI

logger = get_logger("vision_node")


# ---------------------------------------------------------------------
# Vision Node
# ---------------------------------------------------------------------
async def vision_node(state):
    """Analyze the image and return structured details + sales bullets."""

    # Use shared context for everything else
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

    extended_schema = """
    {
      "item_type": "comic | card | record | toy | other",
      "title": "",
      "series": "",
      "issue_number": "",
      "variant_type": "",
      "legacy_number_or_code": "",
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

    if item_type == "comic":
        bullet_instruction = """
        Create exactly 3 short, catchy bullets highlighting collectible appeal:
        characters, cover art, first appearances, or variants.
        Identify variant text near the issue number (e.g., "Variant Edition", "2nd Print")
        and any codes like "LGY#151" or "Direct Edition".
        """
    elif item_type == "card":
        bullet_instruction = """
        Create exactly 3 brief bullets (under 8 words) describing card appeal.
        Mention rarity (Common, Rare, Ultra Rare, etc.), holo type, or set.
        Focus on fine print at the bottom edge for card number (e.g., "032/086")
        and rarity symbols (★ Rare, ◆ Uncommon, ● Common).
        """
    elif item_type == "record":
        bullet_instruction = """
        Create exactly 3 short bullets for vinyl records:
        mention artist, genre, label (e.g., Columbia, RCA), notable songs, or if it’s a reissue.
        """
    else:
        bullet_instruction = """
        Create exactly 3 short bullets describing appeal or condition
        for an antique booth shopper (under 10 words each).
        Mention material, craftsmanship, or era if visible.
        """

    prompt = f"""
    You are a professional collectibles cataloging expert and marketing copywriter.
    Analyze the provided image of a {item_type} and return structured details.

    Respond ONLY with valid JSON matching this structure:
    {extended_schema}

    Notes:
    - Extract visible identifiers (titles, numbers, rarity marks, or artist info).
    - For comics: detect variant text or LGY# codes near the issue number.
    - For cards: read fine print at bottom for set name, card number, and rarity.
    - For records: extract artist, album title, label (e.g., Columbia), year, and genre.
    - Grade condition using collector terms (Near Mint, Very Fine, etc.).
    - Include a full descriptive "raw_summary" (2–3 sentences) explaining what’s visible,
      such as variant markings, card holo type, or record label and sleeve details.
      This text will be shown later as "AI Notes" in the app.
    - {bullet_instruction}
    - Ensure exactly 3 bullets.
    """

    # --------------------------------------------------------------
    # Force GPT-5-Vision for image analysis only
    # --------------------------------------------------------------
    client = AsyncOpenAI()
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    image_url = f"data:image/jpeg;base64,{image_b64}"

    try:
        logger.info("[VisionNode] 🚀 Using GPT-5-Vision for image OCR")
        response = await client.chat.completions.create(
            model="gpt-5-mini",
            messages=[
                {"role": "system", "content": "You are a structured collectibles cataloging expert."},
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ]}
            ],
            response_format={"type": "json_object"},
        )
        text = response.choices[0].message.content
        vision_data = json.loads(text)
        logger.info("[VisionNode DEBUG] Raw vision_data: %s", json.dumps(vision_data, indent=2))
    except Exception as e:
        logger.warning(f"[VisionNode] ⚠️ GPT-5-Vision failed ({e}), retrying with shared context.")
        try:
            response = await llm.ainvoke([HumanMessage(
                content=[{"type": "text", "text": prompt},
                         {"type": "image_url", "image_url": {"url": image_url}}]
            )])
            text = getattr(response, "content", str(response)).strip()
            json_blocks = re.findall(r"\{.*?\}", text, re.DOTALL)
            json_text = max(json_blocks, key=len)
            vision_data = json.loads(json_text)
        except Exception as e2:
            logger.warning(f"[VisionNode] ⚠️ Vision fallback also failed: {e2}")
            vision_data = {"raw_summary": f"Vision extraction error: {e2}", "sales_bullets": ["", "", ""]}

    # --------------------------------------------------------------
    # Regex + heuristic cleanup
    # --------------------------------------------------------------
    vision_data = postprocess_vision_data(vision_data)

    # --------------------------------------------------------------
    # Normalize + map results
    # --------------------------------------------------------------
    title = vision_data.get("title") or "Untitled"
    issue_number = vision_data.get("issue_number") or ""
    variant = vision_data.get("variant_type") or vision_data.get("legacy_number_or_code") or ""
    publisher = vision_data.get("publisher_or_brand") or "Unknown"
    condition = vision_data.get("condition_estimate") or "Unspecified"
    barcode = vision_data.get("barcode_or_isbn") or ""
    rarity = vision_data.get("rarity_or_limited_info") or vision_data.get("rarity_symbol") or ""
    set_name = vision_data.get("set_name") or vision_data.get("series") or ""
    card_number = vision_data.get("card_number") or ""

    if not card_number:
        match = re.search(r"\d{1,3}/\d{1,3}", json.dumps(vision_data))
        if match:
            card_number = match.group(0)

    holo_type = vision_data.get("holo_type") or ""
    artist = vision_data.get("artist_or_band") or vision_data.get("cover_artist_or_label") or ""
    genre = vision_data.get("genre") or ""
    year = vision_data.get("release_year") or ""
    label = vision_data.get("label") or vision_data.get("publisher_or_brand") or vision_data.get("cover_artist_or_label") or ""
    subtype = vision_data.get("series") or vision_data.get("publisher_or_brand") or ""
    ai_notes = vision_data.get("raw_summary") or "No AI notes provided."

    bullets = [b.strip().capitalize() for b in (vision_data.get("sales_bullets") or []) if b.strip()]
    while len(bullets) < 3:
        bullets.append("")
    bullets = bullets[:3]

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
        "year": year,
        "label": label,
        "subtype": subtype,
        "bullet1": bullets[0],
        "bullet2": bullets[1],
        "bullet3": bullets[2],
        "ai_notes": ai_notes,
        "vision_summary": vision_data.get("raw_summary") or "",
        "category_hint": item_type,
        "vision_fields": vision_data,
    }

    current_item = build_display_and_search_strings(current_item)

    logger.info(
        f"[VisionNode] ✅ {current_item.get('display_string')} | "
        f"{publisher or 'Unknown'} | {condition or 'Unspecified'} | "
        f"Bullets: {bullets}"
    )
    logger.info(f"[VisionNode] 🧠 AI Notes: {ai_notes[:200]}")

    return {
        **state,
        "current_item": current_item,
        "messages": state.get("messages", []),
    }


# ---------------------------------------------------------------------
# 🔧 Regex & heuristic post-processing
# ---------------------------------------------------------------------
def postprocess_vision_data(vision_data: dict) -> dict:
    """Repair missing fields using regex and heuristics."""

    blob = json.dumps(vision_data).lower()

    # --- Issue number
    if not vision_data.get("issue_number") or vision_data.get("issue_number") in ["", "n/a"]:
        # skip LGY# but catch normal #
        match = re.search(r"(?<!lgy)#\s?(\d{1,4})(?=[\s\)\-]|$)", blob)
        if match:
            vision_data["issue_number"] = match.group(1)
            logger.info(f"[VisionFix] 🆔 Extracted issue_number #{match.group(1)} via regex fallback")
        elif "guardians of the galaxy" in blob:
            vision_data["issue_number"] = "1"
            logger.info("[VisionFix] ⚙️ Fallback issue_number → #1 (relaunch assumption)")

    # --- Variant detection
    if "variant" in blob and "variant" not in (vision_data.get("variant_type") or "").lower():
        vision_data["variant_type"] = "Variant Edition"
        logger.info("[VisionFix] 🖼️ Detected variant edition from text")
    elif "direct edition" in blob:
        vision_data["variant_type"] = "Direct Edition"
    elif re.search(r"1st print|first print", blob):
        vision_data["variant_type"] = "1st Print"

    # --- Publisher fill
    if not vision_data.get("publisher_or_brand") or vision_data.get("publisher_or_brand") in ["", "n/a"]:
        if "marvel" in blob:
            vision_data["publisher_or_brand"] = "Marvel"
        elif "dc" in blob:
            vision_data["publisher_or_brand"] = "DC Comics"
        elif "image comics" in blob:
            vision_data["publisher_or_brand"] = "Image Comics"
        elif "idw" in blob:
            vision_data["publisher_or_brand"] = "IDW Publishing"

    if vision_data.get("variant_type"):
        vision_data["variant_type"] = vision_data["variant_type"].title()

    return vision_data
