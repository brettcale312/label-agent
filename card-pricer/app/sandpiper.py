"""
sandpiper.py
------------
Sandpiper API integration — authentication, item creation, and barcode retrieval.
Adapted from label-agent/app/sandpiper.py (removed utils.logger dependency).
"""

import os
import json
import time
import logging
import httpx

logger = logging.getLogger("sandpiper")

_cached_token: str | None = None
_cached_expiry: float = 0

# Duplicate suppression: track recent payloads for 10 seconds
_recent_payloads: dict[str, float] = {}
DUPLICATE_COOLDOWN = 10


# ─────────────────────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────────────────────

async def _login() -> str:
    global _cached_token, _cached_expiry

    now = time.time()
    if _cached_token and now < _cached_expiry:
        return _cached_token

    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://app.sandpiperhq.com/api/login/do-login",
            json={
                "username": os.getenv("SANDPIPER_USERNAME"),
                "password": os.getenv("SANDPIPER_PASSWORD"),
            },
            timeout=20,
        )
        r.raise_for_status()
        token = r.json().get("jwtToken")
        if not token:
            raise ValueError("No token in Sandpiper login response")

    _cached_token = token
    _cached_expiry = now + 3600
    logger.info("[sandpiper] Login successful")
    return token


# ─────────────────────────────────────────────────────────────────────────────
# Item creation + barcode
# ─────────────────────────────────────────────────────────────────────────────

async def create_item_and_barcode(
    inv_num: str,
    description: str,
    price_dollars: float,
) -> str:
    """
    Create an inventory item in Sandpiper and return its barcode string.
    Returns "#" if barcode generation fails, None if duplicate suppressed.
    """
    global _recent_payloads

    now = time.time()
    payload_key = json.dumps(
        {"inv": inv_num, "desc": description.strip(), "price": round(price_dollars, 2)},
        sort_keys=True,
    )

    # Clean old entries
    _recent_payloads = {k: v for k, v in _recent_payloads.items() if now - v < DUPLICATE_COOLDOWN}

    if payload_key in _recent_payloads:
        logger.warning(f"[sandpiper] Duplicate suppressed for {inv_num}")
        return None

    _recent_payloads[payload_key] = now

    token = await _login()
    account_id = os.getenv("SANDPIPER_ACCOUNT_ID")
    booth = os.getenv("SANDPIPER_BOOTH")
    headers = {"Authorization": f"Bearer {token}"}

    # ── Step 1: Create item ───────────────────────────────────────────────────
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"https://app.sandpiperhq.com/api/items/v2/{account_id}/create?quantity=1",
            json={
                "id": "",
                "inventoryNumber": inv_num,
                "description": description[:80],
                "acquired": int(time.time()),
                "originalCost": 0,
                "totalCost": 0,
                "askingPrice": int(round(price_dollars * 100)),
            },
            headers=headers,
            timeout=20,
        )
        r.raise_for_status()
        ids = r.json()
        if not ids or not isinstance(ids, list):
            raise ValueError(f"Unexpected create item response: {r.text}")
        item_id = ids[0]
        logger.info(f"[sandpiper] Created item id={item_id}")

    # ── Step 2: Generate barcode ──────────────────────────────────────────────
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://app.sandpiperhq.com/api/barcodes/generate-ids-text",
            json={
                "template": "30up",
                "skip": 0,
                "ids": [item_id],
                "boothNumber": booth,
                "currency": "USD",
                "printAll": False,
                "accountId": account_id,
            },
            headers=headers,
            timeout=20,
        )
        r.raise_for_status()
        barcode_req_id = r.text.strip().strip('"')

    # ── Step 3: Retrieve barcode text ─────────────────────────────────────────
    retrieve_url = f"https://app.sandpiperhq.com/api/barcodes/retrieve-text?id={barcode_req_id}"

    async with httpx.AsyncClient() as client:
        r = await client.get(retrieve_url, headers=headers, timeout=20)
        r.raise_for_status()
        text = r.text.strip()

        lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
        if not lines:
            logger.info("[sandpiper] Empty barcode on first try — retrying in 5s")
            import asyncio
            await asyncio.sleep(5)
            r = await client.get(retrieve_url, headers=headers, timeout=20)
            r.raise_for_status()
            text = r.text.strip()
            lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]

        if not lines:
            logger.error("[sandpiper] No barcode lines found after retry")
            return "#"

        fields = lines[0].split()
        barcode = fields[0] if fields and fields[0].isdigit() else "#"
        logger.info(f"[sandpiper] Barcode: {barcode}")
        return barcode


# ─────────────────────────────────────────────────────────────────────────────
# Price updates (post-upload edits)
# ─────────────────────────────────────────────────────────────────────────────

async def _find_item_id(inv_num: str) -> str | None:
    """Look up a Sandpiper item id from its inventory number."""
    token = await _login()
    account_id = os.getenv("SANDPIPER_ACCOUNT_ID")
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"https://app.sandpiperhq.com/api/items/v2/{account_id}/search",
            params={"inventoryNumber": inv_num},
            headers=headers,
            timeout=20,
        )
        r.raise_for_status()
        results = r.json()

    if not results:
        return None
    if isinstance(results, list):
        for item in results:
            if item.get("inventoryNumber") == inv_num:
                return item.get("id")
        return results[0].get("id") if results else None
    if isinstance(results, dict):
        return results.get("id")
    return None


async def update_price(inv_num: str, new_price_dollars: float) -> bool:
    """
    Update the asking price of an already-uploaded Sandpiper item.
    Returns True on success, False on failure. Logs details on error.
    """
    if not inv_num:
        logger.warning("[sandpiper] update_price called with empty inv_num")
        return False

    token = await _login()
    account_id = os.getenv("SANDPIPER_ACCOUNT_ID")
    headers = {"Authorization": f"Bearer {token}"}

    item_id = await _find_item_id(inv_num)
    if not item_id:
        logger.warning(f"[sandpiper] update_price: item not found for inv {inv_num}")
        return False

    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"https://app.sandpiperhq.com/api/items/v2/{account_id}/update",
            json={
                "id": item_id,
                "inventoryNumber": inv_num,
                "askingPrice": int(round(new_price_dollars * 100)),
            },
            headers=headers,
            timeout=20,
        )

    if r.status_code >= 400:
        logger.error(f"[sandpiper] update_price failed ({r.status_code}): {r.text[:200]}")
        return False

    logger.info(f"[sandpiper] Updated price for {inv_num} → ${new_price_dollars:.2f}")
    return True
