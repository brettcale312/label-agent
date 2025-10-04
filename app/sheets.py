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

    # Debug (optional):
    # log_path = os.path.join(LOG_DIR, f"sheets_payload_{_ts()}.json")
    # with open(log_path, "w", encoding="utf-8") as f:
    #     json.dump(payload, f, ensure_ascii=False, indent=2)
    # print(f"[DEBUG][sheets] sending payload → {log_path}")
    # print(f"[DEBUG][sheets] POST {url}")

    async with httpx.AsyncClient(follow_redirects=True) as client:
        r = await client.post(url, json=payload, timeout=20)
        try:
            r.raise_for_status()
        except Exception as e:
            # Debug (optional):
            # print(f"[ERROR][sheets] {e}, status={r.status_code}, response={r.text[:200]}")
            raise

        try:
            resp_json = r.json()
        except Exception:
            resp_json = {"raw_text": r.text}

        # Debug (optional):
        # resp_path = os.path.join(LOG_DIR, f"sheets_response_{_ts()}.json")
        # with open(resp_path, "w", encoding="utf-8") as f:
        #     json.dump(resp_json, f, ensure_ascii=False, indent=2)
        # print(f"[DEBUG][sheets] wrote response → {resp_path}")

        return resp_json
