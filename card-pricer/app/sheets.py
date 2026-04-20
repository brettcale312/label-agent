"""
sheets.py
---------
Google Sheets integration via Apps Script webhook.
Adapted from label-agent/app/sheets.py (unchanged logic, removed unused imports).
"""

import os
import re
import time
import logging
import httpx

logger = logging.getLogger("sheets")

# Columns sent to Google Sheets for card rows (must match Apps Script expectations)
CARD_COLUMNS = [
    "Title",
    "Bullet 1",
    "Bullet 2",
    "Price Source",
    "Price",
    "Inventory #",
    "Barcode",
    "Condition",
    "Base_Price",
    "AI Notes",
]


async def append_row(fields: dict) -> dict:
    """
    Send a card row to Google Sheets via Apps Script webhook.
    Only sends the columns defined in CARD_COLUMNS.
    """
    url = os.getenv("APPS_SCRIPT_WEBHOOK")
    if not url:
        logger.warning("[sheets] No APPS_SCRIPT_WEBHOOK configured")
        return {"error": "no webhook configured"}

    # Build ordered payload matching Apps Script expectations
    ordered = {col: fields.get(col, "") for col in CARD_COLUMNS}

    async with httpx.AsyncClient(follow_redirects=True) as client:
        r = await client.post(url, json={"type": "card", "fields": ordered}, timeout=20)
        try:
            r.raise_for_status()
        except Exception as e:
            logger.error(f"[sheets] append_row error: {e}")
            raise

        try:
            return r.json()
        except Exception:
            return {"raw_text": r.text}


async def get_next_inventory_number() -> str:
    """
    Fetch the next sequential inventory number from the Apps Script.
    Falls back to a timestamp-based ID if unavailable.
    """
    url = os.getenv("APPS_SCRIPT_WEBHOOK")
    if not url:
        logger.warning("[sheets] No APPS_SCRIPT_WEBHOOK — using fallback inventory #")
        return f"CRD-{int(time.time()) % 100000}"

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            r = await client.get(url, params={"type": "card"}, timeout=10)
            r.raise_for_status()

            try:
                data = r.json()
                text = (
                    data.get("next") or data.get("inventory") or data.get("number") or ""
                    if isinstance(data, dict)
                    else str(data)
                )
            except Exception:
                text = r.text.strip()

            text = text.strip().strip('"').replace("\\n", "").replace("\\r", "")

            # Strip HTML if Apps Script returned it
            if "<" in text:
                text = re.sub(r"<[^>]+>", "", text).strip()

            if text and any(c.isdigit() for c in text):
                logger.info(f"[sheets] Inventory #: {text!r}")
                return text

            logger.warning(f"[sheets] Invalid inventory # response: {text!r}")
    except Exception as e:
        logger.warning(f"[sheets] Could not fetch inventory #: {e}")

    return f"CRD-{int(time.time()) % 100000}"
