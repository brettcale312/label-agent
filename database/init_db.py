from .connection import create_tables, get_db_session, engine
from .models import Base
from .operations import UserPreferenceOps
from utils.logger import get_logger

logger = get_logger(__name__)

def initialize_database(reset: bool = False):
    """Initialize or reset the database with tables and default data."""
    try:
        if reset:
            logger.warning("⚠️ Reset mode enabled: dropping all tables first...")
            Base.metadata.drop_all(bind=engine)

        create_tables()
        logger.info("Database tables created successfully")

        db = get_db_session()
        try:
            default_user = UserPreferenceOps.get_user_preferences(db, "default_user")
            logger.info(f"Default user preferences ensured: {default_user}")
        finally:
            db.close()

        logger.info("Database initialization completed successfully")
        return True
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        return False

if __name__ == "__main__":
    import sys
    reset_mode = "--reset" in sys.argv
    initialize_database(reset=reset_mode)
