"""
LangGraph tools for pricing operations.
These tools will be used by the LangGraph agent to perform pricing tasks.
"""

from typing import Dict, Any, Optional, List
from langchain_core.tools import tool
from database.connection import get_db_session
from database.operations import (
    PricingSessionOps, ItemOps, LearnedPatternOps, 
    UserPreferenceOps, PricingCacheOps
)
from pricing_tools.pricing_model import get_best_price
from utils.logger import get_logger

logger = get_logger(__name__)


@tool
def search_ebay_prices(item_title: str, item_type: str, condition: Optional[str] = None) -> Dict[str, Any]:
    """
    Search eBay for pricing data for an item.
    
    Args:
        item_title: The title/name of the item to search for
        item_type: Type of item (comic, record, card, anything)
        condition: Optional condition of the item
    
    Returns:
        Dictionary with pricing data including median_price, avg_price, sample_count
    """
    try:
        # Check cache first
        db = get_db_session()
        try:
            cached_result = PricingCacheOps.get_cached_result(
                db, item_title, item_type, condition, "ebay"
            )
            if cached_result:
                logger.info(f"Using cached eBay result for: {item_title}")
                return {"source": "cache", "data": cached_result}
        finally:
            db.close()
        
        # Get fresh pricing data
        result = get_best_price(
            title=item_title,
            category=item_type,
            condition=condition or "good",
            venue="antique_store"
        )
        
        if result:
            # Cache the result
            db = get_db_session()
            try:
                PricingCacheOps.cache_result(
                    db, item_title, item_type, result, condition, "ebay"
                )
            finally:
                db.close()
            
            return {"source": "ebay_api", "data": result}
        else:
            return {"source": "none", "data": None}
            
    except Exception as e:
        logger.error(f"Error searching eBay prices: {e}")
        return {"source": "error", "data": None, "error": str(e)}


@tool
def search_discogs_prices(item_title: str, artist: Optional[str] = None) -> Dict[str, Any]:
    """
    Search Discogs for pricing data for a record.
    
    Args:
        item_title: The title of the record
        artist: Optional artist name
    
    Returns:
        Dictionary with Discogs pricing data
    """
    try:
        # Check cache first
        db = get_db_session()
        try:
            cached_result = PricingCacheOps.get_cached_result(
                db, item_title, "record", None, "discogs"
            )
            if cached_result:
                logger.info(f"Using cached Discogs result for: {item_title}")
                return {"source": "cache", "data": cached_result}
        finally:
            db.close()
        
        # Get fresh Discogs data
        result = get_best_price(
            title=item_title,
            artist=artist,
            category="record",
            condition="good",
            venue="antique_store"
        )
        
        if result:
            # Cache the result
            db = get_db_session()
            try:
                PricingCacheOps.cache_result(
                    db, item_title, "record", result, None, "discogs"
                )
            finally:
                db.close()
            
            return {"source": "discogs_api", "data": result}
        else:
            return {"source": "none", "data": None}
            
    except Exception as e:
        logger.error(f"Error searching Discogs prices: {e}")
        return {"source": "error", "data": None, "error": str(e)}


@tool
def search_web_prices(item_title: str, item_type: str) -> Dict[str, Any]:
    """
    Search the web for pricing data using Brave Search.
    
    Args:
        item_title: The title/name of the item to search for
        item_type: Type of item (comic, record, card, anything)
    
    Returns:
        Dictionary with web search pricing data
    """
    try:
        # Check cache first
        db = get_db_session()
        try:
            cached_result = PricingCacheOps.get_cached_result(
                db, item_title, item_type, None, "brave_search"
            )
            if cached_result:
                logger.info(f"Using cached web search result for: {item_title}")
                return {"source": "cache", "data": cached_result}
        finally:
            db.close()
        
        # Get fresh web search data
        result = get_best_price(
            title=item_title,
            category=item_type,
            condition="good",
            venue="antique_store"
        )
        
        if result:
            # Cache the result
            db = get_db_session()
            try:
                PricingCacheOps.cache_result(
                    db, item_title, item_type, result, None, "brave_search"
                )
            finally:
                db.close()
            
            return {"source": "web_search", "data": result}
        else:
            return {"source": "none", "data": None}
            
    except Exception as e:
        logger.error(f"Error searching web prices: {e}")
        return {"source": "error", "data": None, "error": str(e)}


@tool
def get_learned_patterns(pattern_type: str, pattern_key: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Retrieve learned patterns from previous pricing sessions.
    
    Args:
        pattern_type: Type of pattern to retrieve (series_pricing, condition_multiplier, etc.)
        pattern_key: Optional specific pattern key to filter by
    
    Returns:
        List of learned patterns with their data and confidence scores
    """
    try:
        db = get_db_session()
        try:
            if pattern_key:
                pattern = LearnedPatternOps.get_pattern_by_key(db, pattern_type, pattern_key)
                if pattern:
                    return [{
                        "pattern_type": pattern.pattern_type,
                        "pattern_key": pattern.pattern_key,
                        "pattern_data": pattern.pattern_data,
                        "confidence_score": pattern.confidence_score,
                        "sample_size": pattern.sample_size
                    }]
                else:
                    return []
            else:
                patterns = LearnedPatternOps.get_patterns_by_type(db, pattern_type)
                return [{
                    "pattern_type": p.pattern_type,
                    "pattern_key": p.pattern_key,
                    "pattern_data": p.pattern_data,
                    "confidence_score": p.confidence_score,
                    "sample_size": p.sample_size
                } for p in patterns]
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Error retrieving learned patterns: {e}")
        return []


@tool
def save_learned_pattern(session_id: int, pattern_type: str, pattern_key: str, 
                        pattern_data: Dict[str, Any], confidence_score: float = 0.0, 
                        sample_size: int = 1) -> Dict[str, Any]:
    """
    Save a new learned pattern from pricing analysis.
    
    Args:
        session_id: ID of the current pricing session
        pattern_type: Type of pattern (series_pricing, condition_multiplier, etc.)
        pattern_key: Unique key for this pattern
        pattern_data: The pattern data to store
        confidence_score: Confidence in this pattern (0.0 to 1.0)
        sample_size: Number of items this pattern is based on
    
    Returns:
        Dictionary with success status and pattern ID
    """
    try:
        db = get_db_session()
        try:
            pattern = LearnedPatternOps.create_pattern(
                db, session_id, pattern_type, pattern_key, 
                pattern_data, confidence_score, sample_size
            )
            return {
                "success": True,
                "pattern_id": pattern.id,
                "message": f"Saved pattern: {pattern_type} - {pattern_key}"
            }
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Error saving learned pattern: {e}")
        return {"success": False, "error": str(e)}


@tool
def get_user_preferences(user_id: str) -> Dict[str, Any]:
    """
    Get user preferences for pricing and display.
    
    Args:
        user_id: The user ID to get preferences for
    
    Returns:
        Dictionary with user preferences
    """
    try:
        db = get_db_session()
        try:
            prefs = UserPreferenceOps.get_user_preferences(db, user_id)
            return {
                "default_venue": prefs.default_venue,
                "conservative_pricing": prefs.conservative_pricing,
                "auto_round_prices": prefs.auto_round_prices,
                "preferred_condition_order": prefs.preferred_condition_order
            }
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Error getting user preferences: {e}")
        return {"error": str(e)}


@tool
def save_priced_item(session_id: int, item_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Save a priced item to the database.
    
    Args:
        session_id: ID of the current pricing session
        item_data: Dictionary with item information and pricing results
    
    Returns:
        Dictionary with success status and item ID
    """
    try:
        db = get_db_session()
        try:
            item = ItemOps.create_item(db, session_id, item_data)
            
            # Update session activity
            PricingSessionOps.update_session_activity(db, session_id)
            
            return {
                "success": True,
                "item_id": item.id,
                "message": f"Saved item: {item.title}"
            }
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Error saving priced item: {e}")
        return {"success": False, "error": str(e)}


@tool
def get_session_history(session_id: int) -> List[Dict[str, Any]]:
    """
    Get the history of items processed in a pricing session.
    
    Args:
        session_id: ID of the pricing session
    
    Returns:
        List of items with their pricing data
    """
    try:
        db = get_db_session()
        try:
            items = ItemOps.get_items_by_session(db, session_id)
            return [{
                "id": item.id,
                "item_type": item.item_type,
                "title": item.title,
                "condition": item.condition,
                "base_price": item.base_price,
                "final_price": item.final_price,
                "pricing_reasoning": item.pricing_reasoning,
                "ai_notes": item.ai_notes,
                "created_at": item.created_at.isoformat() if item.created_at else None
            } for item in items]
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Error getting session history: {e}")
        return []


# Export all tools for easy importing
pricing_tools = [
    search_ebay_prices,
    search_discogs_prices,
    search_web_prices,
    get_learned_patterns,
    save_learned_pattern,
    get_user_preferences,
    save_priced_item,
    get_session_history
]
