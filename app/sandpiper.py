import os
import httpx
import time
import json

# Simple in-memory token cache
_cached_token = None
_cached_expiry = 0

# Optional debug toggle (set DEBUG_LOGS=true in .env if you ever want verbose logs)
DEBUG_LOGS = os.getenv("DEBUG_LOGS", "false").lower() == "true"


def _log(msg):
    """Append timestamped log entries to daily logs/sandpiper_YYYYMMDD.log"""
    os.makedirs("logs", exist_ok=True)
    ts = time.strftime("[%Y-%m-%d %H:%M:%S]")
    date = time.strftime("%Y%m%d")
    log_path = os.path.join("logs", f"sandpiper_{date}.log")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"{ts} {msg}\n")


async def _login():
    """Authenticate with Sandpiper API and cache token (in memory only)."""
    global _cached_token, _cached_expiry
    now = time.time()
    if _cached_token and now < _cached_expiry:
        return _cached_token  # still valid

    url = "https://app.sandpiperhq.com/api/login/do-login"
    payload = {
        "username": os.getenv("SANDPIPER_USERNAME"),
        "password": os.getenv("SANDPIPER_PASSWORD"),
    }

    async with httpx.AsyncClient() as client:
        r = await client.post(url, json=payload, timeout=20)
        r.raise_for_status()
        data = r.json()
        token = data.get("jwtToken")
        if not token:
            raise ValueError("No token in Sandpiper login response")
        _cached_token = token
        _cached_expiry = now + 3600  # 1 hour
        _log("LOGIN → success")
        return token


async def create_item_and_barcode(inv_num: str, description: str, price_dollars: float):
    """Create inventory item, generate barcode, and return the numeric code."""
    token = await _login()
    account_id = os.getenv("SANDPIPER_ACCOUNT_ID")
    booth = os.getenv("SANDPIPER_BOOTH")
    headers = {"Authorization": f"Bearer {token}"}

    # Step 1 – Create item
    create_url = f"https://app.sandpiperhq.com/api/items/v2/{account_id}/create?quantity=1"
    item_payload = {
        "id": "",
        "inventoryNumber": inv_num,
        "description": description[:80],
        "acquired": int(time.time()),
        "originalCost": 0,
        "totalCost": 0,
        "askingPrice": int(round(price_dollars * 100)),  # convert to cents
    }

    if DEBUG_LOGS:
        _log(f"REQUEST → {json.dumps({'inv_num': inv_num, 'desc': description, 'price': price_dollars})}")

    async with httpx.AsyncClient() as client:
        r = await client.post(create_url, json=item_payload, headers=headers, timeout=20)
        r.raise_for_status()
        ids = r.json()
        _log(f"CREATE RESPONSE → {r.text.strip()}")
        if not ids or not isinstance(ids, list):
            raise ValueError(f"Unexpected create item response: {r.text}")
        item_id = ids[0]
        _log(f"CREATE ITEM → id={item_id}")

    # Step 2 – Generate barcode
    gen_url = "https://app.sandpiperhq.com/api/barcodes/generate-ids-text"
    gen_payload = {
        "template": "30up",
        "skip": 0,
        "ids": [item_id],
        "boothNumber": booth,
        "currency": "USD",
        "printAll": False,
        "accountId": account_id,
    }

    if DEBUG_LOGS:
        _log(f"BARCODE REQUEST → {json.dumps(gen_payload)}")

    async with httpx.AsyncClient() as client:
        r = await client.post(gen_url, json=gen_payload, headers=headers, timeout=20)
        r.raise_for_status()
        barcode_req_id = r.text.strip().strip('"')
        _log(f"BARCODE GEN RESPONSE → {barcode_req_id}")

    # Step 3 – Retrieve barcode text (conditional retry)
    retrieve_url = f"https://app.sandpiperhq.com/api/barcodes/retrieve-text?id={barcode_req_id}"
    async with httpx.AsyncClient() as client:
        r = await client.get(retrieve_url, headers=headers, timeout=20)
        r.raise_for_status()
        text = r.text.strip()
        _log(f"RETRIEVE RAW → {text}")

        # Parse barcode lines
        lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
        if not lines:
            _log("ℹ️ Empty barcode text on first try — waiting 5 seconds...")
            time.sleep(5)
            r = await client.get(retrieve_url, headers=headers, timeout=20)
            r.raise_for_status()
            text = r.text.strip()
            _log(f"RETRIEVE RETRY RAW → {text}")
            lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]

        if not lines:
            _log("❌ No valid barcode lines found after retry")
            return "#"

        # Example: "18017172\t718-5492\t718\tItem desc\t$5.00"
        fields = lines[0].split()
        barcode = fields[0] if fields and fields[0].isdigit() else "#"
        _log(f"✅ FINAL BARCODE → {barcode}")
        return barcode
