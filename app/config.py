import os
from dotenv import load_dotenv

load_dotenv()

APPS_SCRIPT_WEBHOOK = os.getenv("APPS_SCRIPT_WEBHOOK", "").strip()
if not APPS_SCRIPT_WEBHOOK:
    # Allow running without webhook (e.g., for local dev); main will warn
    pass
