import os, json, datetime, time
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
        print("[WARN] No APPS_SCRIPT_WEBHOOK configured")
        return f"{type_[:3].upper()}-{int(time.time()) % 10000}"

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            r = await client.get(url, params={"type": type_}, timeout=10)
            r.raise_for_status()

            # Try JSON first
            try:
                data = r.json()
                if isinstance(data, dict):
                    text = (
                        data.get("next")
                        or data.get("inventory")
                        or data.get("number")
                        or ""
                    )
                else:
                    text = str(data).strip()
            except Exception:
                text = r.text.strip()

            # Clean output
            text = text.strip().strip('"').replace("\\n", "").replace("\\r", "")
            print(f"[DEBUG] Apps Script raw returned: '{text}' for type '{type_}'")

            # If the script returned HTML or weird wrapping, attempt to isolate the number
            if "<" in text or ">" in text:
                # crude HTML strip
                import re

                text = re.sub(r"<[^>]+>", "", text).strip()

            # Check validity
            if not text or not any(c.isdigit() for c in text):
                print(f"[WARN] Apps Script gave invalid text: '{text}'")
                return f"{type_[:3].upper()}-{int(time.time()) % 10000}"

            print(f"[INFO] ✅ Clean inventory number: '{text}'")
            return text
    except Exception as e:
        print(f"[WARN] could not fetch next inventory #: {e}")
        return f"{type_[:3].upper()}-{int(time.time()) % 10000}"
