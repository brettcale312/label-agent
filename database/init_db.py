"""
Initialize the database with tables and initial data.
"""

from .connection import create_tables, get_db_session
from .operations import UserPreferenceOps
from utils.logger import get_logger

logger = get_logger(__name__)


def initialize_database():
    """Initialize the database with tables and default data."""
    try:
        # Create all tables
        create_tables()
        logger.info("Database tables created successfully")
        
        # Create default user preferences if needed
        db = get_db_session()
        try:
            # Create default user preferences for a default user
            default_user = UserPreferenceOps.get_user_preferences(db, "default_user")
            logger.info(f"Default user preferences created: {default_user}")
        except Exception as e:
            logger.error(f"Error creating default user preferences: {e}")
        finally:
            db.close()
            
        logger.info("Database initialization completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        return False


if __name__ == "__main__":
    initialize_database()
