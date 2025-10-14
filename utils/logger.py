"""
utils/logger.py
---------------
Global logging setup shared across all modules.
Creates daily log files and auto-cleans older ones.
"""

import logging
import os
import datetime
from glob import glob

# --- Configuration ---
LOG_DIR = "logs"
LOG_RETENTION_DAYS = 14  # delete logs older than this many days
os.makedirs(LOG_DIR, exist_ok=True)

# Use environment variable to control verbosity
# Example: set ENV=prod to disable console logging
ENV = os.getenv("ENV", "dev").lower()  # "dev" or "prod"


def _cleanup_old_logs():
    """Remove log files older than retention period."""
    cutoff = datetime.datetime.now() - datetime.timedelta(days=LOG_RETENTION_DAYS)
    for path in glob(os.path.join(LOG_DIR, "*.log")):
        try:
            timestamp_str = os.path.basename(path).split("_")[-1].replace(".log", "")
            if len(timestamp_str) == 8:
                date = datetime.datetime.strptime(timestamp_str, "%Y%m%d")
                if date < cutoff:
                    os.remove(path)
        except Exception:
            continue


def get_logger(name: str) -> logging.Logger:
    """
    Returns a configured logger for the given module name.
    Logs to logs/<name>_YYYYMMDD.log and auto-cleans older logs.
    Console output is disabled when ENV=prod.
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        logger.setLevel(logging.INFO)
        log_path = os.path.join(LOG_DIR, f"{name}_{datetime.datetime.now():%Y%m%d}.log")
        handler = logging.FileHandler(log_path)
        handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s"))
        logger.addHandler(handler)

        # Optional console output (disabled in production)
        if ENV != "prod":
            console = logging.StreamHandler()
            console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
            logger.addHandler(console)

        _cleanup_old_logs()

    return logger
