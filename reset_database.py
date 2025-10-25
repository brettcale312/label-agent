"""
reset_database.py
-----------------
Fully resets the local SQLite database used by Label-Agent
using the canonical database.init_db.initialize_database(reset=True).
If RESET_AGENT_CACHE=true in the environment, it also clears
LangGraph and LangChain caches so the next run starts pristine.
"""

import os
import shutil
import tempfile
from dotenv import load_dotenv
from sqlalchemy import text
from database.connection import get_db_session
from database.init_db import initialize_database
from utils.logger import get_logger

# ---------------------------------------------------------------------
# INITIAL SETUP
# ---------------------------------------------------------------------
load_dotenv()
logger = get_logger("reset_database")


# ---------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------
def flush_sessions():
    """Remove all PricingAgent session data for a clean start."""
    try:
        db = get_db_session()
        db.execute(text("DELETE FROM pricing_sessions;"))
        db.commit()
        print("🧹 Flushed all PricingAgent sessions.")
        logger.info("Flushed all PricingAgent sessions.")
    except Exception as e:
        logger.warning(f"⚠️ Could not flush sessions: {e}")
        print(f"⚠️ Could not flush sessions: {e}")
    finally:
        db.close()


def purge_langgraph_cache():
    """Delete all LangGraph / LangChain cache folders."""
    for p in [
        ".langgraph_cache",
        ".langchain",
        os.path.join(tempfile.gettempdir(), "langgraph"),
        os.path.join(os.getenv("LOCALAPPDATA", ""), "langgraph"),
    ]:
        try:
            if p and os.path.exists(p):
                shutil.rmtree(p, ignore_errors=True)
                print(f"🧨 Cleared cache: {p}")
        except Exception as e:
            print(f"⚠️ Could not remove {p}: {e}")


# ---------------------------------------------------------------------
# MAIN RESET FUNCTION
# ---------------------------------------------------------------------
def reset_database():
    """Reinitialize DB schema and optionally purge caches."""
    print("🗑️ Reinitializing database via init_db.py ...")
    success = initialize_database(reset=True)

    if success:
        print("✅ Database recreated successfully!")
    else:
        print("❌ Database initialization failed! Check logs for details.")

    flush_sessions()

    # If RESET_AGENT_CACHE=true, clear all LangGraph caches
    if os.getenv("RESET_AGENT_CACHE", "").lower() in ("1", "true", "yes", "on"):
        print("🔄 RESET_AGENT_CACHE flag detected — clearing all caches...")
        purge_langgraph_cache()
    else:
        print("💾 RESET_AGENT_CACHE not set — keeping LangGraph caches.")


# ---------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------
if __name__ == "__main__":
    reset_database()
