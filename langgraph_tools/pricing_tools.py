"""
LangGraph tools for pricing, eBay lookups, and database operations.
These tools are registered with the LangGraph ToolNode and can be called
automatically by the PricingAgent or manually for testing and persistence.
"""

from typing import Dict, Any, Optional, List
from langchain_core.tools import tool
from database.connection import get_db_session
from database.operations import (
    PricingSessionOps, ItemOps, LearnedPatternOps, UserPreferenceOps,
)
from utils.logger import get_logger
import os
from pricing_tools.ebay import search_ebay

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Knowledge & Database Tools
# ---------------------------------------------------------------------------

@tool
def get_learned_patterns(pattern_type: str, pattern_key: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve learned pricing patterns from previous sessions."""
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
def save_learned_pattern(
    session_id: int,
    pattern_type: str,
    pattern_key: str,
    pattern_data: Dict[str, Any],
    confidence_score: float = 0.0,
    sample_size: int = 1,
) -> Dict[str, Any]:
    """Save a new learned pricing pattern to the database."""
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
    """Retrieve a user's stored pricing and display preferences."""
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
    """Save a priced item and update the session's last activity timestamp."""
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
    """Retrieve all items priced within a given session."""
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
# Tool Registration
# ---------------------------------------------------------------------------

pricing_tools = [
    get_learned_patterns,
    save_learned_pattern,
    get_user_preferences,
    save_priced_item,
    get_session_history,
]

ENABLE_EBAY_TOOL = os.getenv("ENABLE_EBAY_TOOL", "true").lower() in ("true", "1", "yes")

if ENABLE_EBAY_TOOL:
    pricing_tools.append(search_ebay)
    logger.info("[PricingTools] ENABLE_EBAY_TOOL=true — eBay tool registered")
else:
    logger.info("[PricingTools] ENABLE_EBAY_TOOL not set — eBay tool disabled")

# ---------------------------------------------------------------------------
# Helper Function
# ---------------------------------------------------------------------------

def get_tool_by_name(name: str):
    """Return a tool object by its registered name (for manual lookup)."""
    for t in pricing_tools:
        if getattr(t, "name", None) == name:
            return t
    return None
