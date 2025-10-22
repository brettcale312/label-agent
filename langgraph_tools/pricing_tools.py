"""
LangGraph tools for pricing and vision operations.
These tools are used by the LangGraph agent to perform analysis and pricing tasks.
"""

from typing import Dict, Any, Optional, List
from langchain_core.tools import tool
from database.connection import get_db_session
from database.operations import (
    PricingSessionOps, ItemOps, LearnedPatternOps, UserPreferenceOps
)
from utils.logger import get_logger
from io import BytesIO
from PIL import Image
from openai import OpenAI
import base64
import json
import os

logger = get_logger(__name__)
client = OpenAI()

# ---------------------------------------------------------------------------
# Vision Analysis Tool
# ---------------------------------------------------------------------------

@tool
def analyze_image_with_vision(image_base64: Any, item_type: str) -> Dict[str, Any]:
    """
    Analyze an image using the OpenAI Vision model to extract relevant details.
    Returns structured JSON with basic title, condition, and notes.
    """
    try:
        logger.info(f"[VISION] Starting analysis for type={item_type}")

        # --- Normalize input ---
        if isinstance(image_base64, Image.Image):
            buf = BytesIO()
            image_base64.convert("RGB").save(buf, format="JPEG", quality=85)
            img_bytes = buf.getvalue()

        elif isinstance(image_base64, (bytes, bytearray)):
            img_bytes = bytes(image_base64)

        elif isinstance(image_base64, str):
            logger.info(f"[VISION] Detected string input length={len(image_base64):,}")
            if "," in image_base64:
                _, image_base64 = image_base64.split(",", 1)
            clean_b64 = image_base64.strip().replace("\n", "").replace("\r", "")
            pad = len(clean_b64) % 4
            if pad:
                clean_b64 += "=" * (4 - pad)
            img_bytes = base64.b64decode(clean_b64)
        else:
            return {"success": False, "source": "vision", "error": f"Unsupported type: {type(image_base64)}"}

        if len(img_bytes) < 1000:
            logger.error(f"[VISION] ❌ Too few bytes ({len(img_bytes)}).")
            return {"success": False, "source": "vision", "error": "Image too small or invalid."}

        # --- Preprocess image ---
        image = Image.open(BytesIO(img_bytes)).convert("RGB")
        image.thumbnail((1600, 1600))
        buf = BytesIO()
        image.save(buf, format="JPEG", quality=70, optimize=True)
        jpeg_bytes = buf.getvalue()
        encoded = base64.b64encode(jpeg_bytes).decode("utf-8")
        image_url = f"data:image/jpeg;base64,{encoded}"

        # Save debug preview
        os.makedirs("logs", exist_ok=True)
        debug_path = os.path.join("logs", "debug_vision.jpg")
        with open(debug_path, "wb") as f:
            f.write(jpeg_bytes)
        logger.info(f"[VISION] Saved debug image to {debug_path}")

        # --- Call OpenAI Vision ---
        prompt = (
            f"You are an expert collectible identifier. "
            f"Analyze this image of a {item_type} and extract structured details as JSON:\n"
            f'{{"Title": "", "Condition": "", "Notes": ""}}. '
            f"If unsure, make your best guess but never leave fields blank."
        )

        result = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ],
            temperature=0.2,
        )

        content = result.choices[0].message.content.strip()
        logger.info(f"[VISION] Raw model output: {content}")

        try:
            extracted = json.loads(content)
        except json.JSONDecodeError:
            extracted = {"Title": content, "Condition": "good", "Notes": ""}

        return {"success": True, "source": "vision", "data": extracted}

    except Exception as e:
        logger.error(f"[VISION] Error: {e}")
        return {"success": False, "source": "vision", "error": str(e)}


# ---------------------------------------------------------------------------
# Knowledge & Database Tools
# ---------------------------------------------------------------------------

@tool
def get_learned_patterns(pattern_type: str, pattern_key: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve learned patterns from previous pricing sessions."""
    try:
        db = get_db_session()
        try:
            if pattern_key:
                pattern = LearnedPatternOps.get_pattern_by_key(db, pattern_type, pattern_key)
                return [pattern.__dict__] if pattern else []
            patterns = LearnedPatternOps.get_patterns_by_type(db, pattern_type)
            return [p.__dict__ for p in patterns]
        finally:
            db.close()
    except Exception as e:
        logger.error(f"[TOOLS] Error retrieving learned patterns: {e}")
        return []


@tool
def save_learned_pattern(session_id: int, pattern_type: str, pattern_key: str,
                         pattern_data: Dict[str, Any], confidence_score: float = 0.0,
                         sample_size: int = 1) -> Dict[str, Any]:
    """Save a new learned pattern from pricing analysis."""
    if not all([session_id, pattern_type, pattern_key, pattern_data]):
        return {"success": False, "reason": "invalid arguments"}

    try:
        db = get_db_session()
        try:
            pattern = LearnedPatternOps.create_pattern(
                db, session_id, pattern_type, pattern_key, pattern_data,
                confidence_score, sample_size,
            )
            return {"success": True, "pattern_id": pattern.id}
        finally:
            db.close()
    except Exception as e:
        logger.error(f"[TOOLS] Error saving learned pattern: {e}")
        return {"success": False, "error": str(e)}


@tool
def get_user_preferences(user_id: str) -> Dict[str, Any]:
    """Get user preferences for pricing and display."""
    try:
        db = get_db_session()
        try:
            prefs = UserPreferenceOps.get_user_preferences(db, user_id)
            return {
                "default_venue": prefs.default_venue,
                "conservative_pricing": prefs.conservative_pricing,
                "auto_round_prices": prefs.auto_round_prices,
                "preferred_condition_order": prefs.preferred_condition_order,
            }
        finally:
            db.close()
    except Exception as e:
        logger.error(f"[TOOLS] Error getting user preferences: {e}")
        return {"success": False, "error": str(e)}


@tool
def save_priced_item(session_id: int, item_data: Dict[str, Any]) -> Dict[str, Any]:
    """Save a priced item to the database."""
    try:
        db = get_db_session()
        try:
            item = ItemOps.create_item(db, session_id, item_data)
            PricingSessionOps.update_session_activity(db, session_id)
            return {"success": True, "item_id": item.id}
        finally:
            db.close()
    except Exception as e:
        logger.error(f"[TOOLS] Error saving priced item: {e}")
        return {"success": False, "error": str(e)}


@tool
def get_session_history(session_id: int) -> List[Dict[str, Any]]:
    """Retrieve the item history for a pricing session."""
    try:
        db = get_db_session()
        try:
            items = ItemOps.get_items_by_session(db, session_id)
            return [item.__dict__ for item in items]
        finally:
            db.close()
    except Exception as e:
        logger.error(f"[TOOLS] Error getting session history: {e}")
        return []


# ---------------------------------------------------------------------------
# Export all tools
# ---------------------------------------------------------------------------
pricing_tools = [
    analyze_image_with_vision,
    get_learned_patterns,
    save_learned_pattern,
    get_user_preferences,
    save_priced_item,
    get_session_history,
]
