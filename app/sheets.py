import os, json, datetime
import httpx

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

def _ts():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

async def append_row(type_, fields):
    """Send row to Google Apps Script Webhook"""
    url = os.getenv("APPS_SCRIPT_WEBHOOK")
    payload = {"type": type_, "fields": fields}

    async with httpx.AsyncClient(follow_redirects=True) as client:
        r = await client.post(url, json=payload, timeout=20)
        try:
            r.raise_for_status()
        except Exception as e:
            raise

        try:
            resp_json = r.json()
        except Exception:
            resp_json = {"raw_text": r.text}

        return resp_json


async def get_next_inventory_number(type_: str) -> str:
    """Ask Google Apps Script for the next sequential Inventory #."""
    url = os.getenv("APPS_SCRIPT_WEBHOOK")
    if not url:
        print(f"[WARN] No APPS_SCRIPT_WEBHOOK configured")
        return "TEMP-0001"
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            r = await client.get(url, params={"type": type_}, timeout=10)
            r.raise_for_status()
            text = r.text.strip()
            print(f"[DEBUG] Apps Script returned: '{text}' for type '{type_}'")
            if text and text[0].isdigit():
                return text
            print(f"[WARN] Apps Script response doesn't start with digit: '{text}'")
            return text or "TEMP-0001"
    except Exception as e:
        print(f"[WARN] could not fetch next inventory #: {e}")
        return "TEMP-0001"
