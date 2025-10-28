"""
session_utils.py
----------------
Session management and entry pipeline for the LangGraph Pricing Agent.

Handles:
- Database session creation/retrieval
- Image preprocessing and encoding
- Running the full graph (vision → market → tools → reasoning → valuation → explain)
- Mapping final state into type-specific schema for review.html and Google Sheets
- Async-safe wrapper for FastAPI or CLI contexts
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
from app.models import row_order  # unified schema field order
from schemas.pricing_schemas import get_schema

logger = get_logger("session_utils")


# ---------------------------------------------------------------------
# Session Management
# ---------------------------------------------------------------------
def create_session(user_id: str, session_name: Optional[str] = None) -> int:
    """Create a new pricing session for a user."""
    db = get_db_session()
    try:
        session = PricingSessionOps.create_session(db, user_id, session_name)
        logger.info(f"[Session] Created session {session.id} for {user_id}")
        return session.id
    finally:
        db.close()


def get_or_create_session(user_id: str) -> int:
    """Get the user's active session, or create a new one if none exist."""
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
    """Resize and compress the input image, returning base64-encoded JPEG data."""
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    image.thumbnail((1024, 1024))
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


# ---------------------------------------------------------------------
# Review Field Builder
# ---------------------------------------------------------------------
def build_review_fields(final_state: Dict[str, Any], item_type: str) -> Dict[str, Any]:
    """
    Merge vision, valuation, and explanation data into the structured
    format used by review.html and Sheets.
    """
    logger.debug(f"[SessionUtils] current_item contents: {final_state.get('current_item')}")

    schema = get_schema(item_type)
    current_item = final_state.get("current_item") or {}
    valuation = final_state.get("valuation") or {}
    explanation = final_state.get("explanation") or ""
    market_data = final_state.get("market_data") or {}

    # -----------------------------------------------------------------
    # Determine and format price
    # -----------------------------------------------------------------
    base_price = valuation.get("Base Price") or valuation.get("final_price") or 0.0
    formatted_price = f"{float(base_price):.2f}"

    # Initialize result with blank schema keys to preserve order
    result = {key: "" for key in schema.keys()}

    # -----------------------------------------------------------------
    # Normalize AI Notes
    # -----------------------------------------------------------------
    ai_notes = explanation or current_item.get("vision_summary") or ""
    if isinstance(ai_notes, dict) and "AI Notes" in ai_notes:
        ai_notes = ai_notes["AI Notes"]
    elif isinstance(ai_notes, str) and ai_notes.strip().startswith("{"):
        try:
            parsed = json.loads(ai_notes)
            ai_notes = parsed.get("AI Notes", ai_notes)
        except Exception:
            pass

    # -----------------------------------------------------------------
    # Determine Price Source from actual tools used
    # -----------------------------------------------------------------
    price_source = ", ".join(final_state.get("tool_results", {}).keys()) or "eBay"

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
            "Label": current_item.get("publisher") or "",
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
    # ANYTHING (General)
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
    # Debugging Aid — keep median for transparency
    # -----------------------------------------------------------------
    if "eBay Median" not in result:
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
    """Execute the full pricing pipeline using the compiled LangGraph graph."""
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

    # Build type-specific structured result for review.html
    review_fields = build_review_fields(result, item_type)

    logger.info(f"[Session] ✅ Full pipeline complete for {user_id}")
    logger.info(f"[Session DEBUG] Review field keys: {list(review_fields.keys())}")

    return {
        "success": True,
        "pricing_result": review_fields,
        "tool_results": result.get("tool_results", {}),
        "session_id": session_id,
    }


# ---------------------------------------------------------------------
# Async-Safe Entry Point
# ---------------------------------------------------------------------
def price_item_from_image(graph, user_id: str, image_bytes: bytes, item_type: str) -> Dict[str, Any]:
    """
    Entry point for external calls (e.g. FastAPI route or CLI).
    Handles image conversion and runs the async pricing pipeline.
    Automatically detects whether it's running inside an existing event loop.
    """
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
            logger.info("[Session] 🔄 Reusing existing event loop (FastAPI mode)")
            nest_asyncio.apply()
            return loop.run_until_complete(_runner())
        else:
            logger.info("[Session] 🆕 Starting new event loop (CLI/test mode)")
            return asyncio.run(_runner())

    except Exception as e:
        logger.error(f"[Session] ❌ Error in price_item_from_image: {e}")
        return {"success": False, "error": str(e)}
