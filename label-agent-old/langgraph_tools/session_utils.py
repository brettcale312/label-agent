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
from utils.normalizers import extract_price_sources, clean_ai_notes
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
    """Resize and compress image, returning base64-encoded JPEG."""
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    image.thumbnail((1024, 1024))
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


# ---------------------------------------------------------------------
# Review Field Builder
# ---------------------------------------------------------------------
def build_review_fields(final_state: Dict[str, Any], item_type: str) -> Dict[str, Any]:
    """Merge LangGraph output into schema-friendly review structure."""
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
    # AI NOTES
    # -----------------------------------------------------------------
    ai_notes_raw = (
        current_item.get("ai_notes")
        or current_item.get("vision_fields", {}).get("raw_summary")
        or current_item.get("vision_summary")
        or explanation
        or ""
    )
    ai_notes = clean_ai_notes(ai_notes_raw)
    logger.info(f"[SessionUtils] 🧠 AI Notes restored, length={len(ai_notes)} chars")

    # -----------------------------------------------------------------
    # PRICE SOURCE — assign before schema usage
    # -----------------------------------------------------------------
    price_source = extract_price_sources(final_state.get("tool_results", {}))
    logger.info(f"[SessionUtils] 💰 Price sources: {price_source}")

    # -----------------------------------------------------------------
    # COMMON FIELD SET
    # -----------------------------------------------------------------
    common_fields = {
        "Price Source": price_source,
        "Base Price": formatted_price,
        "Condition": current_item.get("condition") or "",
        "Price": formatted_price,
        "Inventory #": current_item.get("inventory_number") or "",
        "Barcode": current_item.get("barcode") or "",
        "AI Notes": ai_notes,
    }

    # -----------------------------------------------------------------
    # ITEM TYPE BRANCHES
    # -----------------------------------------------------------------
    if item_type == "comic":
        result.update({
            "Title": current_item.get("display_string") or current_item.get("title") or "Untitled Comic",
            "Bullet 1": current_item.get("bullet1") or "",
            "Bullet 2": current_item.get("bullet2") or "",
            "Bullet 3": current_item.get("bullet3") or "",
            "Publisher": current_item.get("publisher") or "",
            **common_fields,
        })

    elif item_type == "card":
        result.update({
            "Title": current_item.get("display_string") or current_item.get("title") or "Trading Card",
            "Bullet 1": current_item.get("bullet1") or "",
            "Bullet 2": current_item.get("bullet2") or "",
            "Bullet 3": current_item.get("bullet3") or "",
            "Set": current_item.get("set_name") or "",
            "Number": current_item.get("card_number") or "",
            "Rarity": current_item.get("rarity") or "",
            **common_fields,
        })

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
            **common_fields,
        })

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
            **common_fields,
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
# Pipeline Runner (Multi-image aware)
# ---------------------------------------------------------------------
async def run_pricing_pipeline(
    graph,
    user_id: str,
    image_b64_list: list[str],
    item_type: str,
    extra_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Execute LangGraph pipeline with one or more images."""
    session_id = get_or_create_session(user_id)

    # If only one image was passed, normalize into list
    if isinstance(image_b64_list, str):
        image_b64_list = [image_b64_list]

    # Build multi-image messages
    messages = [
        HumanMessage(
            content=[
                {"type": "text", "text": f"Please analyze and price this {item_type}."},
                *[
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                    for img_b64 in image_b64_list
                ],
            ]
        )
    ]

    # Construct graph state
    state = {
        "messages": messages,
        "session_id": session_id,
        "user_id": user_id,
        "current_item": {"type": item_type},
        "item_type": item_type,
    }

    # Merge in any optional extras
    if extra_state:
        state.update(extra_state)

    logger.info(f"[Session] ▶️ Starting pipeline for {user_id}, session {session_id}, images={len(image_b64_list)}")

    # Run async LangGraph
    result = await graph.ainvoke(state)

    # Filter out nested tool data
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
# Sync Wrapper (Multi-image aware)
# ---------------------------------------------------------------------
def price_item_from_image(
    graph,
    user_id: str,
    image_bytes: bytes | list[bytes],
    item_type: str,
    extra_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Sync wrapper for async pipeline (supports one or multiple images)."""
    import nest_asyncio
    try:
        # Normalize to list
        if isinstance(image_bytes, (bytes, bytearray)):
            image_bytes = [image_bytes]

        # Preprocess and encode each image
        image_b64_list = [preprocess_image(b) for b in image_bytes]

        async def _runner():
            return await run_pricing_pipeline(
                graph,
                user_id,
                image_b64_list,
                item_type,
                extra_state=extra_state,
            )

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
