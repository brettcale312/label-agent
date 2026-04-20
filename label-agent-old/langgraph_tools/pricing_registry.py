"""
pricing_registry.py
-------------------
LangGraph database & persistence tool registry.

These tools allow the PricingAgent (or future nodes)
to read and write from your database, persist session data,
and manage user preferences or learned pricing patterns.

➡ Currently optional — the active pricing pipeline uses
   only market data tools from `pricing_tools/search_registry.py`.

Import example (for persistence nodes or learning agents):
    from langgraph_tools.pricing_registry import PRICING_DB_TOOLS
"""

from typing import Dict, Any, Optional, List
from langchain_core.tools import tool
from database.connection import get_db_session
from database.operations import (
    PricingSessionOps,
    ItemOps,
    LearnedPatternOps,
    UserPreferenceOps,
)
from utils.logger import get_logger

logger = get_logger("pricing_registry")


# ---------------------------------------------------------------------------
# 🔍 Learned Pattern Tools
# ---------------------------------------------------------------------------

@tool("get_learned_patterns")
def get_learned_patterns(pattern_type: str, pattern_key: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve learned pricing patterns or heuristics from past sessions."""
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
        logger.error(f"[get_learned_patterns] {e}")
        return []


@tool("save_learned_pattern")
def save_learned_pattern(
    session_id: int,
    pattern_type: str,
    pattern_key: str,
    pattern_data: Dict[str, Any],
    confidence_score: float = 0.0,
    sample_size: int = 1,
) -> Dict[str, Any]:
    """Save a new learned pricing pattern for AI model fine-tuning or analytics."""
    if not all([session_id, pattern_type, pattern_key, pattern_data]):
        return {"success": False, "reason": "missing arguments"}

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
        logger.error(f"[save_learned_pattern] {e}")
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# 👤 User Preference Tools
# ---------------------------------------------------------------------------

@tool("get_user_preferences")
def get_user_preferences(user_id: str) -> Dict[str, Any]:
    """Retrieve stored preferences for a given user (venue defaults, rounding, etc.)."""
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
        logger.error(f"[get_user_preferences] {e}")
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# 💾 Session & Item Persistence Tools
# ---------------------------------------------------------------------------

@tool("save_priced_item")
def save_priced_item(session_id: int, item_data: Dict[str, Any]) -> Dict[str, Any]:
    """Persist a priced item to the database and update its session activity timestamp."""
    try:
        db = get_db_session()
        try:
            item = ItemOps.create_item(db, session_id, item_data)
            PricingSessionOps.update_session_activity(db, session_id)
            return {"success": True, "item_id": item.id}
        finally:
            db.close()
    except Exception as e:
        logger.error(f"[save_priced_item] {e}")
        return {"success": False, "error": str(e)}


@tool("get_session_history")
def get_session_history(session_id: int) -> List[Dict[str, Any]]:
    """Fetch all items priced within a given session."""
    try:
        db = get_db_session()
        try:
            items = ItemOps.get_items_by_session(db, session_id)
            return [item.__dict__ for item in items]
        finally:
            db.close()
    except Exception as e:
        logger.error(f"[get_session_history] {e}")
        return []


# ---------------------------------------------------------------------------
# 🔧 Tool Registry
# ---------------------------------------------------------------------------

PRICING_DB_TOOLS = [
    get_learned_patterns,
    save_learned_pattern,
    get_user_preferences,
    save_priced_item,
    get_session_history,
]


def get_tool_by_name(name: str):
    """Return a tool object by its registered name (for manual lookup or testing)."""
    for t in PRICING_DB_TOOLS:
        if getattr(t, "name", None) == name:
            return t
    return None
