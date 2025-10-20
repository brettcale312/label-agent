"""
SQLAlchemy models for the pricing agent database.
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, ForeignKey, JSON, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class PricingSession(Base):
    """Represents a pricing session - could be a single user session or a batch of items."""
    __tablename__ = 'pricing_sessions'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(String(100), nullable=False)  # Could be user identifier
    session_name = Column(String(200), nullable=True)  # Optional session name
    started_at = Column(DateTime, default=datetime.utcnow)
    last_activity = Column(DateTime, default=datetime.utcnow)
    status = Column(String(50), default='active')  # active, completed, archived
    total_items_processed = Column(Integer, default=0)
    session_notes = Column(Text, nullable=True)
    
    # Relationships
    items = relationship("Item", back_populates="session", cascade="all, delete-orphan")
    learned_patterns = relationship("LearnedPattern", back_populates="session", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<PricingSession(id={self.id}, user_id='{self.user_id}', status='{self.status}')>"


class Item(Base):
    """Represents a single item that was priced."""
    __tablename__ = 'items'
    
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey('pricing_sessions.id'), nullable=False)
    
    # Item identification
    item_type = Column(String(50), nullable=False)  # comic, record, card, anything
    title = Column(String(500), nullable=False)
    condition = Column(String(100), nullable=True)
    
    # Pricing data
    base_price = Column(Float, nullable=True)  # eBay median or base price
    final_price = Column(Float, nullable=False)
    pricing_reasoning = Column(Text, nullable=True)
    ai_notes = Column(Text, nullable=True)
    
    # Metadata
    barcode = Column(String(100), nullable=True)
    publisher = Column(String(200), nullable=True)
    artist = Column(String(200), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    session = relationship("PricingSession", back_populates="items")
    
    def __repr__(self):
        return f"<Item(id={self.id}, type='{self.item_type}', title='{self.title[:50]}...')>"


class LearnedPattern(Base):
    """Represents patterns learned during pricing sessions."""
    __tablename__ = 'learned_patterns'
    
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey('pricing_sessions.id'), nullable=False)
    
    # Pattern identification
    pattern_type = Column(String(100), nullable=False)  # series_pricing, condition_multiplier, genre_trend
    pattern_key = Column(String(200), nullable=False)  # e.g., "TMNT Adventures", "vg condition", "comics"
    
    # Pattern data
    pattern_data = Column(JSON, nullable=False)  # Flexible JSON structure
    confidence_score = Column(Float, default=0.0)  # 0.0 to 1.0
    sample_size = Column(Integer, default=1)  # Number of items this pattern is based on
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    session = relationship("PricingSession", back_populates="learned_patterns")
    
    def __repr__(self):
        return f"<LearnedPattern(type='{self.pattern_type}', key='{self.pattern_key}', confidence={self.confidence_score})>"


class UserPreference(Base):
    """User-specific preferences and settings."""
    __tablename__ = 'user_preferences'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(String(100), nullable=False, unique=True)
    
    # Pricing preferences
    default_venue = Column(String(50), default='antique_store')  # antique_store, ebay, etc.
    conservative_pricing = Column(Boolean, default=False)
    auto_round_prices = Column(Boolean, default=True)
    
    # UI preferences
    preferred_condition_order = Column(JSON, nullable=True)  # Custom condition display order
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<UserPreference(user_id='{self.user_id}', venue='{self.default_venue}')>"


class PricingCache(Base):
    """Cache for expensive pricing lookups to avoid repeated API calls."""
    __tablename__ = 'pricing_cache'
    
    id = Column(Integer, primary_key=True)
    
    # Cache key
    search_query = Column(String(500), nullable=False)
    item_type = Column(String(50), nullable=False)
    condition = Column(String(100), nullable=True)
    
    # Cached results
    cached_result = Column(JSON, nullable=False)
    cache_timestamp = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)  # When this cache entry expires
    
    # Metadata
    source = Column(String(50), nullable=False)  # ebay, discogs, brave_search
    
    def __repr__(self):
        return f"<PricingCache(query='{self.search_query[:50]}...', source='{self.source}')>"
