"""
Database connection and session management.
Adds lightweight logging for connection lifecycle events.
"""

import os
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from .models import Base

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Database Configuration
# ---------------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./pricing_agent.db")

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
        echo=False,  # Set to True to see raw SQL queries
    )
else:
    engine = create_engine(DATABASE_URL, echo=False)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
logger.info(f"[DB-CONN] Engine initialized → {DATABASE_URL}")


# ---------------------------------------------------------------------------
# Table Initialization
# ---------------------------------------------------------------------------
def create_tables():
    """Create all database tables."""
    Base.metadata.create_all(bind=engine)
    logger.info("[DB-CONN] ✅ All tables created successfully.")
    print("✅ Database tables created successfully")


# ---------------------------------------------------------------------------
# Session Helpers
# ---------------------------------------------------------------------------
def get_db() -> Session:
    """
    Dependency for FastAPI routes.
    Yields a session and ensures cleanup on request end.
    """
    db = SessionLocal()
    logger.info("[DB-CONN] Opened new session (FastAPI)")
    try:
        yield db
    finally:
        db.close()
        logger.info("[DB-CONN] Closed session (FastAPI)")


def get_db_session() -> Session:
    """
    Direct session accessor for internal use (LangGraph tools, scripts, etc.).
    Remember to close manually!
    """
    logger.info("[DB-CONN] Opened new session (direct)")
    return SessionLocal()


# ---------------------------------------------------------------------------
# Manual Execution
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    create_tables()
