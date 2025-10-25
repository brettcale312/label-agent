"""
utils/logger.py
---------------
Global logging setup shared across all modules.
Creates daily log files and auto-cleans older ones.
"""

import logging
import os
import datetime
import sys, io
from glob import glob

# --- UTF-8 console fix ---
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception as e:
        print(f"UTF-8 console reconfigure failed: {e}")

# --- Configuration ---
LOG_DIR = "logs"
LOG_RETENTION_DAYS = 14
os.makedirs(LOG_DIR, exist_ok=True)

# Environment modes: dev, prod, debug
ENV = os.getenv("ENV", "dev").lower()
LOG_LEVEL = logging.DEBUG if ENV == "debug" else logging.INFO


def _cleanup_old_logs():
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
    Console verbosity controlled by ENV (dev/prod/debug).
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(LOG_LEVEL)
        log_path = os.path.join(LOG_DIR, f"{name}_{datetime.datetime.now():%Y%m%d}.log")

        # --- File handler ---
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(LOG_LEVEL)
        file_handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s"))
        logger.addHandler(file_handler)

        # --- Console handler ---
        if ENV != "prod":
            console = logging.StreamHandler()
            console_formatter = logging.Formatter("%(levelname)s: %(message)s")
            console.setFormatter(console_formatter)
            console.setLevel(logging.DEBUG if ENV == "debug" else logging.INFO)
            logger.addHandler(console)

        _cleanup_old_logs()

    return logger
