"""
session_utils.py
----------------
Session management and entry pipeline for the LangGraph Pricing Agent.
"""

import io
import base64
import asyncio
import json
from typing import Dict, Any, Optional
from PIL import Image
from langchain_core.messages import HumanMessage
from database.connection import get_db_session
from database.operations import PricingSessionOps
from utils.logger import get_logger
from app.models import row_order
from schemas.pricing_schemas import get_schema

logger = get_logger("session_utils")


# ---------------------------------------------------------------------
# Session Management
# ---------------------------------------------------------------------
def create_session(user_id: str, session_name: Optional[str] = None) -> int:
    db = get_db_session()
    try:
        session = PricingSessionOps.create_session(db, user_id, session_name)
        logger.info(f"[Session] Created session {session.id} for {user_id}")
        return session.id
    finally:
        db.close()


def get_or_create_session(user_id: str) -> int:
    db = get_db_session()
    try:
        session = PricingSessionOps.get_active_session(db, user_id)
        if session:
            logger.info(f"[Session] Using existing session {session.id} for {user_id}")
            return session.id
        return create_session(user_id)
    finally:
        db.close()


# ---------------------------------------------------------------------
# Image Preprocessing
# ---------------------------------------------------------------------
def preprocess_image(image_bytes: bytes) -> str:
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    image.thumbnail((1024, 1024))
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


# ---------------------------------------------------------------------
# Review Field Builder
# ---------------------------------------------------------------------
def build_review_fields(final_state: Dict[str, Any], item_type: str) -> Dict[str, Any]:
    schema = get_schema(item_type)
    current_item = final_state.get("current_item") or {}
    valuation = final_state.get("valuation") or {}
    explanation = final_state.get("explanation") or ""
    market_data = final_state.get("market_data") or {}

    # -----------------------------------------------------------------
    # Format price
    # -----------------------------------------------------------------
    base_price = valuation.get("Base Price") or valuation.get("final_price") or 0.0
    formatted_price = f"{float(base_price):.2f}"

    # Initialize blank result to preserve order
    result = {key: "" for key in schema.keys()}

    # -----------------------------------------------------------------
    # AI NOTES - use full descriptive raw_summary again
    # -----------------------------------------------------------------
    ai_notes = (
        current_item.get("ai_notes")
        or current_item.get("vision_fields", {}).get("raw_summary")
        or current_item.get("vision_summary")
        or explanation
        or ""
    )
    if isinstance(ai_notes, (dict, list)):
        ai_notes = json.dumps(ai_notes, ensure_ascii=False)
    ai_notes = str(ai_notes).strip()
    logger.info(f"[SessionUtils] 🧠 AI Notes restored, length={len(ai_notes)} chars")

    # -----------------------------------------------------------------
    # PRICE SOURCE - use legacy-friendly keys, fallback to mappings
    # -----------------------------------------------------------------
    tool_results = final_state.get("tool_results", {}) or {}
    keys = list(tool_results.keys())

    # Use legacy behavior: join raw keys first
    price_source = ", ".join(keys) or "eBay"

    # Apply readable mappings if possible
    price_source = (
        price_source.replace("search_ebay", "eBay")
        .replace("search_discogs", "Discogs")
        .replace("search_mycomicshop", "MyComicShop")
        .replace("search_gocollect", "GoCollect")
        .replace("search_tcgplayer", "TCGPlayer")
    )

    # Filter out temporary LangGraph tool IDs like "Toolu 1"
    if "Toolu" in price_source:
        mapped = []
        for k in keys:
            lk = k.lower()
            if "ebay" in lk:
                mapped.append("eBay")
            elif "discogs" in lk:
                mapped.append("Discogs")
            elif "comic" in lk:
                mapped.append("MyComicShop")
            elif "gocollect" in lk:
                mapped.append("GoCollect")
            elif "tcg" in lk:
                mapped.append("TCGPlayer")
        price_source = ", ".join(sorted(set(mapped))) or "eBay"

        # -----------------------------------------------------------------
        # COMIC
        # -----------------------------------------------------------------
        if item_type == "comic":
            result.update({
                "Title": current_item.get("display_string") or current_item.get("title") or "Untitled Comic",
                "Bullet 1": current_item.get("bullet1") or "",
                "Bullet 2": current_item.get("bullet2") or "",
                "Bullet 3": current_item.get("bullet3") or "",
                "Publisher": current_item.get("publisher") or "",
                "Price Source": price_source,
                "Base Price": formatted_price,
                "Condition": current_item.get("condition") or "",
                "Price": formatted_price,
                "Inventory #": current_item.get("inventory_number") or "",
                "Barcode": current_item.get("barcode") or "",
                "AI Notes": ai_notes,
            })

    # -----------------------------------------------------------------
    # CARD
    # -----------------------------------------------------------------
    elif item_type == "card":
        result.update({
            "Title": current_item.get("display_string") or current_item.get("title") or "Trading Card",
            "Bullet 1": current_item.get("bullet1") or "",
            "Bullet 2": current_item.get("bullet2") or "",
            "Bullet 3": current_item.get("bullet3") or "",
            "Set": current_item.get("set_name") or "",
            "Number": current_item.get("card_number") or "",
            "Rarity": current_item.get("rarity") or "",
            "Price Source": price_source,
            "Base Price": formatted_price,
            "Condition": current_item.get("condition") or "",
            "Price": formatted_price,
            "Inventory #": current_item.get("inventory_number") or "",
            "Barcode": current_item.get("barcode") or "",
            "AI Notes": ai_notes,
        })

    # -----------------------------------------------------------------
    # RECORD
    # -----------------------------------------------------------------
    elif item_type == "record":
        result.update({
            "Title": current_item.get("display_string") or current_item.get("title") or "Vinyl Record",
            "Artist": current_item.get("artist") or "",
            "Label": current_item.get("label") or current_item.get("publisher") or "",
            "Year": current_item.get("year") or "",
            "Genre": current_item.get("genre") or "",
            "Bullet 1": current_item.get("bullet1") or "",
            "Bullet 2": current_item.get("bullet2") or "",
            "Bullet 3": current_item.get("bullet3") or "",
            "Price Source": price_source,
            "Base Price": formatted_price,
            "Condition": current_item.get("condition") or "",
            "Price": formatted_price,
            "Inventory #": current_item.get("inventory_number") or "",
            "Barcode": current_item.get("barcode") or "",
            "AI Notes": ai_notes,
        })

    # -----------------------------------------------------------------
    # ANYTHING
    # -----------------------------------------------------------------
    else:
        result.update({
            "Title": current_item.get("display_string") or current_item.get("title") or "Misc Item",
            "Category": current_item.get("category_hint") or "general",
            "Description": current_item.get("vision_summary") or "",
            "Material": current_item.get("material") or "",
            "Era": current_item.get("era") or "",
            "Bullet 1": current_item.get("bullet1") or "",
            "Bullet 2": current_item.get("bullet2") or "",
            "Bullet 3": current_item.get("bullet3") or "",
            "Price Source": price_source,
            "Base Price": formatted_price,
            "Condition": current_item.get("condition") or "",
            "Price": formatted_price,
            "Inventory #": current_item.get("inventory_number") or "",
            "Barcode": current_item.get("barcode") or "",
            "AI Notes": ai_notes,
        })

    # -----------------------------------------------------------------
    # Transparency field
    # -----------------------------------------------------------------
    result["eBay Median"] = (
        market_data.get("ebay", {}).get("median")
        or market_data.get("ebay", {}).get("average")
        or ""
    )

    logger.info(f"[SessionUtils] ✅ Review fields built for {item_type}: {result.get('Title')}")
    return result


# ---------------------------------------------------------------------
# Pipeline Runner
# ---------------------------------------------------------------------
async def run_pricing_pipeline(graph, user_id: str, image_b64: str, item_type: str) -> Dict[str, Any]:
    session_id = get_or_create_session(user_id)
    messages = [
        HumanMessage(
            content=[
                {"type": "text", "text": f"Please analyze and price this {item_type}."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}
            ]
        )
    ]

    state = {
        "messages": messages,
        "session_id": session_id,
        "user_id": user_id,
        "current_item": {"type": item_type},
    }

    logger.info(f"[Session] ▶️ Starting pipeline for {user_id}, session {session_id}")
    result = await graph.ainvoke(state)

    # Prevent nested tool details from being dumped into review
    result["tool_results"] = {
        k: v for k, v in (result.get("tool_results") or {}).items() if isinstance(v, dict)
    }

    review_fields = build_review_fields(result, item_type)

    logger.info(f"[Session] ✅ Full pipeline complete for {user_id}")
    return {
        "success": True,
        "pricing_result": review_fields,
        "tool_results": result.get("tool_results", {}),
        "session_id": session_id,
    }


# ---------------------------------------------------------------------
# Async Entry Point
# ---------------------------------------------------------------------
def price_item_from_image(graph, user_id: str, image_bytes: bytes, item_type: str) -> Dict[str, Any]:
    import nest_asyncio
    try:
        image_b64 = preprocess_image(image_bytes)

        async def _runner():
            return await run_pricing_pipeline(graph, user_id, image_b64, item_type)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            nest_asyncio.apply()
            return loop.run_until_complete(_runner())
        else:
            return asyncio.run(_runner())

    except Exception as e:
        logger.error(f"[Session] ❌ Error in price_item_from_image: {e}")
        return {"success": False, "error": str(e)}
