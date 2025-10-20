"""
Database operations for the pricing agent.
"""

from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc
from .models import PricingSession, Item, LearnedPattern, UserPreference, PricingCache


class PricingSessionOps:
    """Operations for managing pricing sessions."""
    
    @staticmethod
    def create_session(db: Session, user_id: str, session_name: Optional[str] = None) -> PricingSession:
        """Create a new pricing session."""
        session = PricingSession(
            user_id=user_id,
            session_name=session_name,
            started_at=datetime.utcnow(),
            last_activity=datetime.utcnow(),
            status='active'
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        return session
    
    @staticmethod
    def get_active_session(db: Session, user_id: str) -> Optional[PricingSession]:
        """Get the most recent active session for a user."""
        return db.query(PricingSession).filter(
            and_(
                PricingSession.user_id == user_id,
                PricingSession.status == 'active'
            )
        ).order_by(desc(PricingSession.started_at)).first()
    
    @staticmethod
    def get_session_by_id(db: Session, session_id: int) -> Optional[PricingSession]:
        """Get a session by its ID."""
        return db.query(PricingSession).filter(PricingSession.id == session_id).first()
    
    @staticmethod
    def update_session_activity(db: Session, session_id: int):
        """Update the last activity timestamp for a session."""
        session = db.query(PricingSession).filter(PricingSession.id == session_id).first()
        if session:
            session.last_activity = datetime.utcnow()
            session.total_items_processed += 1
            db.commit()
    
    @staticmethod
    def complete_session(db: Session, session_id: int):
        """Mark a session as completed."""
        session = db.query(PricingSession).filter(PricingSession.id == session_id).first()
        if session:
            session.status = 'completed'
            session.last_activity = datetime.utcnow()
            db.commit()


class ItemOps:
    """Operations for managing items."""
    
    @staticmethod
    def create_item(db: Session, session_id: int, item_data: Dict[str, Any]) -> Item:
        """Create a new item record."""
        item = Item(
            session_id=session_id,
            item_type=item_data.get('item_type'),
            title=item_data.get('title'),
            condition=item_data.get('condition'),
            base_price=item_data.get('base_price'),
            final_price=item_data.get('final_price'),
            pricing_reasoning=item_data.get('pricing_reasoning'),
            ai_notes=item_data.get('ai_notes'),
            barcode=item_data.get('barcode'),
            publisher=item_data.get('publisher'),
            artist=item_data.get('artist')
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item
    
    @staticmethod
    def get_items_by_session(db: Session, session_id: int) -> List[Item]:
        """Get all items for a specific session."""
        return db.query(Item).filter(Item.session_id == session_id).order_by(Item.created_at).all()
    
    @staticmethod
    def get_recent_items(db: Session, user_id: str, limit: int = 10) -> List[Item]:
        """Get recent items across all sessions for a user."""
        return db.query(Item).join(PricingSession).filter(
            PricingSession.user_id == user_id
        ).order_by(desc(Item.created_at)).limit(limit).all()


class LearnedPatternOps:
    """Operations for managing learned patterns."""
    
    @staticmethod
    def create_pattern(db: Session, session_id: int, pattern_type: str, pattern_key: str, 
                      pattern_data: Dict[str, Any], confidence_score: float = 0.0, 
                      sample_size: int = 1) -> LearnedPattern:
        """Create a new learned pattern."""
        pattern = LearnedPattern(
            session_id=session_id,
            pattern_type=pattern_type,
            pattern_key=pattern_key,
            pattern_data=pattern_data,
            confidence_score=confidence_score,
            sample_size=sample_size
        )
        db.add(pattern)
        db.commit()
        db.refresh(pattern)
        return pattern
    
    @staticmethod
    def get_patterns_by_type(db: Session, pattern_type: str) -> List[LearnedPattern]:
        """Get all patterns of a specific type."""
        return db.query(LearnedPattern).filter(
            LearnedPattern.pattern_type == pattern_type
        ).order_by(desc(LearnedPattern.confidence_score)).all()
    
    @staticmethod
    def get_pattern_by_key(db: Session, pattern_type: str, pattern_key: str) -> Optional[LearnedPattern]:
        """Get a specific pattern by type and key."""
        return db.query(LearnedPattern).filter(
            and_(
                LearnedPattern.pattern_type == pattern_type,
                LearnedPattern.pattern_key == pattern_key
            )
        ).first()
    
    @staticmethod
    def update_pattern_confidence(db: Session, pattern_id: int, new_confidence: float, 
                                 additional_sample_size: int = 1):
        """Update a pattern's confidence score and sample size."""
        pattern = db.query(LearnedPattern).filter(LearnedPattern.id == pattern_id).first()
        if pattern:
            # Update confidence and sample size
            pattern.sample_size += additional_sample_size
            pattern.confidence_score = new_confidence
            pattern.last_updated = datetime.utcnow()
            db.commit()


class PricingCacheOps:
    """Operations for managing pricing cache."""
    
    @staticmethod
    def get_cached_result(db: Session, search_query: str, item_type: str, 
                         condition: Optional[str] = None, source: str = "ebay") -> Optional[Dict[str, Any]]:
        """Get a cached pricing result if it exists and hasn't expired."""
        cache_entry = db.query(PricingCache).filter(
            and_(
                PricingCache.search_query == search_query,
                PricingCache.item_type == item_type,
                PricingCache.condition == condition,
                PricingCache.source == source,
                or_(
                    PricingCache.expires_at.is_(None),
                    PricingCache.expires_at > datetime.utcnow()
                )
            )
        ).first()
        
        return cache_entry.cached_result if cache_entry else None
    
    @staticmethod
    def cache_result(db: Session, search_query: str, item_type: str, result: Dict[str, Any],
                    condition: Optional[str] = None, source: str = "ebay", 
                    expires_hours: int = 24):
        """Cache a pricing result."""
        expires_at = datetime.utcnow() + timedelta(hours=expires_hours)
        
        cache_entry = PricingCache(
            search_query=search_query,
            item_type=item_type,
            condition=condition,
            cached_result=result,
            source=source,
            expires_at=expires_at
        )
        db.add(cache_entry)
        db.commit()


class UserPreferenceOps:
    """Operations for managing user preferences."""
    
    @staticmethod
    def get_user_preferences(db: Session, user_id: str) -> Optional[UserPreference]:
        """Get user preferences, creating defaults if they don't exist."""
        prefs = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
        
        if not prefs:
            # Create default preferences
            prefs = UserPreference(user_id=user_id)
            db.add(prefs)
            db.commit()
            db.refresh(prefs)
        
        return prefs
    
    @staticmethod
    def update_user_preferences(db: Session, user_id: str, preferences: Dict[str, Any]):
        """Update user preferences."""
        prefs = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
        
        if prefs:
            for key, value in preferences.items():
                if hasattr(prefs, key):
                    setattr(prefs, key, value)
            prefs.updated_at = datetime.utcnow()
            db.commit()
