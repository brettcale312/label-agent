"""
SQLAlchemy models and unified schema definitions for the pricing agent database.
"""

from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Text, ForeignKey, JSON, Boolean, Index
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()

# ---------------------------------------------------------------------------
# Pricing Session
# ---------------------------------------------------------------------------
class PricingSession(Base):
    """Represents a pricing session - could be a single user session or a batch of items."""
    __tablename__ = "pricing_sessions"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True)
    user_id = Column(String(100), nullable=False)
    session_name = Column(String(200), nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    last_activity = Column(DateTime, default=datetime.utcnow)
    status = Column(String(50), default="active")
    total_items_processed = Column(Integer, default=0)
    session_notes = Column(Text, nullable=True)

    items = relationship("Item", back_populates="session", cascade="all, delete-orphan")
    learned_patterns = relationship("LearnedPattern", back_populates="session", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<PricingSession(id={self.id}, user='{self.user_id}', status='{self.status}')>"

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


# ---------------------------------------------------------------------------
# Item
# ---------------------------------------------------------------------------
class Item(Base):
    """Represents a single item that was priced."""
    __tablename__ = "items"
    __table_args__ = (Index("idx_items_session", "session_id"), {"extend_existing": True})

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("pricing_sessions.id"), nullable=False)

    item_type = Column(String(50), nullable=False)  # comic, record, card, anything
    title = Column(String(500), nullable=False)
    condition = Column(String(100), nullable=True)

    base_price = Column(Float, nullable=True)
    final_price = Column(Float, nullable=False)
    pricing_reasoning = Column(Text, nullable=True)
    ai_notes = Column(Text, nullable=True)

    barcode = Column(String(100), nullable=True)
    publisher = Column(String(200), nullable=True)
    artist = Column(String(200), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    session = relationship("PricingSession", back_populates="items")

    def __repr__(self):
        return f"<Item(id={self.id}, type='{self.item_type}', title='{self.title[:40]}...')>"

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


# ---------------------------------------------------------------------------
# Learned Pattern
# ---------------------------------------------------------------------------
class LearnedPattern(Base):
    """Represents patterns learned during pricing sessions."""
    __tablename__ = "learned_patterns"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("pricing_sessions.id"), nullable=False)

    pattern_type = Column(String(100), nullable=False)
    pattern_key = Column(String(200), nullable=False)
    pattern_data = Column(JSON, nullable=False)
    confidence_score = Column(Float, default=0.0)
    sample_size = Column(Integer, default=1)

    created_at = Column(DateTime, default=datetime.utcnow)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    session = relationship("PricingSession", back_populates="learned_patterns")

    def __repr__(self):
        return f"<LearnedPattern(type='{self.pattern_type}', key='{self.pattern_key}', conf={self.confidence_score:.2f})>"

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


# ---------------------------------------------------------------------------
# User Preferences
# ---------------------------------------------------------------------------
class UserPreference(Base):
    """User-specific preferences and settings."""
    __tablename__ = "user_preferences"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True)
    user_id = Column(String(100), nullable=False, unique=True)

    default_venue = Column(String(50), default="antique_store")
    conservative_pricing = Column(Boolean, default=False)
    auto_round_prices = Column(Boolean, default=True)
    preferred_condition_order = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<UserPreference(user='{self.user_id}', venue='{self.default_venue}')>"

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


# ---------------------------------------------------------------------------
# Pricing Cache
# ---------------------------------------------------------------------------
class PricingCache(Base):
    """Cache for expensive pricing lookups to avoid repeated API calls."""
    __tablename__ = "pricing_cache"
    __table_args__ = (Index("idx_cache_query", "search_query", "source"), {"extend_existing": True})

    id = Column(Integer, primary_key=True)
    search_query = Column(String(500), nullable=False)
    item_type = Column(String(50), nullable=False)
    condition = Column(String(100), nullable=True)
    cached_result = Column(JSON, nullable=False)
    cache_timestamp = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    source = Column(String(50), nullable=False)

    def __repr__(self):
        return f"<PricingCache(query='{self.search_query[:40]}...', source='{self.source}')>"

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


# ---------------------------------------------------------------------------
# SCHEMAS FOR SHEET EXPORT / REVIEW UI
# ---------------------------------------------------------------------------

# --- Comic Books ---
COMIC_SCHEMA: Dict[str, Any] = {
    "Title": "",
    "Bullet 1": "",
    "Bullet 2": "",
    "Bullet 3": "",
    "Publisher": "",
    "Price Source": "",
    "Base Price": "",
    "Condition": "",
    "Price": "",
    "Inventory #": "",
    "Barcode": "",
    "AI Notes": ""
}

# --- Trading Cards ---
CARD_SCHEMA: Dict[str, Any] = {
    "Title": "",
    "Bullet 1": "",
    "Bullet 2": "",
    "Bullet 3": "",
    "Set": "",
    "Number": "",
    "Rarity": "",
    "Price Source": "",
    "Base Price": "",
    "Condition": "",
    "Price": "",
    "Inventory #": "",
    "Barcode": "",
    "AI Notes": ""
}

# --- Vinyl Records ---
RECORD_SCHEMA: Dict[str, Any] = {
    "Title": "",
    "Artist": "",
    "Label": "",
    "Year": "",
    "Genre": "",
    "Bullet 1": "",
    "Bullet 2": "",
    "Bullet 3": "",
    "Price Source": "",
    "Base Price": "",
    "Condition": "",
    "Price": "",
    "Inventory #": "",
    "Barcode": "",
    "AI Notes": ""
}

# --- Generic / “Anything Else” ---
ANYTHING_SCHEMA: Dict[str, Any] = {
    "Title": "",
    "Category": "",
    "Description": "",
    "Material": "",
    "Era": "",
    "Bullet 1": "",
    "Bullet 2": "",
    "Bullet 3": "",
    "Price Source": "",
    "Base Price": "",
    "Condition": "",
    "Price": "",
    "Inventory #": "",
    "Barcode": "",
    "AI Notes": ""
}

# --- Schema Map ---
SCHEMA_MAP = {
    "comic": COMIC_SCHEMA,
    "card": CARD_SCHEMA,
    "record": RECORD_SCHEMA,
    "anything": ANYTHING_SCHEMA
}


def row_order(item_type: str):
    """Return the column order for a given type (used in review.html and Sheets)."""
    return list(SCHEMA_MAP.get(item_type.lower(), ANYTHING_SCHEMA).keys())


# ---------------------------------------------------------------------------
# Ingest Response (for FastAPI return payload)
# ---------------------------------------------------------------------------
class IngestResponse:
    """Standardized response returned after processing an image."""
    def __init__(self, success: bool, review_url: Optional[str] = None, error: Optional[str] = None):
        self.success = success
        self.review_url = review_url
        self.error = error

    def to_dict(self):
        return {"success": self.success, "review_url": self.review_url, "error": self.error}
