"""
sandpiper.py
------------
Sandpiper API integration — authentication, item creation, and barcode retrieval.

Multi-tenant: every call takes an `account_id`. Creds are loaded from the
`accounts` table (Sandpiper password decrypted via app.crypto). JWT tokens are
cached per-account so users from different stores don't collide.
"""

import json
import time
import logging
from typing import Optional, NamedTuple

import httpx

from . import database, crypto

logger = logging.getLogger("sandpiper")


class SandpiperCreds(NamedTuple):
    username: str
    password: str
    account_id: str   # Sandpiper's account id, NOT our DB account.id
    booth: str


def load_creds(db_account_id: int) -> Optional[SandpiperCreds]:
    """Load + decrypt Sandpiper creds for one of our accounts.
    Returns None if any field is missing — caller should treat as "not configured"."""
    acct = database.get_account(db_account_id)
    if not acct:
        return None
    username = acct.get("sandpiper_username")
    encrypted_pw = acct.get("sandpiper_password")
    sp_account_id = acct.get("sandpiper_account_id")
    booth = acct.get("sandpiper_booth")
    if not (username and encrypted_pw and sp_account_id and booth):
        return None
    return SandpiperCreds(
        username=username,
        password=crypto.decrypt(encrypted_pw),
        account_id=sp_account_id,
        booth=booth,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Per-account JWT cache
# ─────────────────────────────────────────────────────────────────────────────

# {db_account_id: (jwt_token, expiry_ts)}
_token_cache: dict[int, tuple[str, float]] = {}

# Per-account duplicate suppression
_recent_payloads: dict[tuple[int, str], float] = {}
DUPLICATE_COOLDOWN = 10


async def _login(db_account_id: int, creds: SandpiperCreds) -> str:
    cached = _token_cache.get(db_account_id)
    now = time.time()
    if cached and now < cached[1]:
        return cached[0]

    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://app.sandpiperhq.com/api/login/do-login",
            json={"username": creds.username, "password": creds.password},
            timeout=20,
        )
        r.raise_for_status()
        token = r.json().get("jwtToken")
        if not token:
            raise ValueError("No token in Sandpiper login response")

    _token_cache[db_account_id] = (token, now + 3600)
    logger.info(f"[sandpiper] Login successful for account {db_account_id}")
    return token


# ─────────────────────────────────────────────────────────────────────────────
# Item creation + barcode
# ─────────────────────────────────────────────────────────────────────────────

async def create_item_and_barcode(
    inv_num: str,
    description: str,
    price_dollars: float,
    db_account_id: int,
) -> Optional[str]:
    """
    Create an inventory item in the account's Sandpiper booth and return its barcode.
    Returns "#" if barcode generation fails, None if duplicate suppressed or creds missing.
    """
    creds = load_creds(db_account_id)
    if not creds:
        logger.warning(f"[sandpiper] No creds for account {db_account_id} — skipping upload")
        return None

    now = time.time()
    payload_key = json.dumps(
        {"inv": inv_num, "desc": description.strip(), "price": round(price_dollars, 2)},
        sort_keys=True,
    )
    cache_key = (db_account_id, payload_key)

    # Clean old entries
    global _recent_payloads
    _recent_payloads = {k: v for k, v in _recent_payloads.items() if now - v < DUPLICATE_COOLDOWN}

    if cache_key in _recent_payloads:
        logger.warning(f"[sandpiper] Duplicate suppressed for {inv_num} (account {db_account_id})")
        return None

    _recent_payloads[cache_key] = now

    token = await _login(db_account_id, creds)
    headers = {"Authorization": f"Bearer {token}"}

    # ── Step 1: Create item ──────────────────────────────────────────────────
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"https://app.sandpiperhq.com/api/items/v2/{creds.account_id}/create?quantity=1",
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
        logger.info(f"[sandpiper] Created item id={item_id} (account {db_account_id})")

    # ── Step 2: Generate barcode ─────────────────────────────────────────────
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://app.sandpiperhq.com/api/barcodes/generate-ids-text",
            json={
                "template": "30up",
                "skip": 0,
                "ids": [item_id],
                "boothNumber": creds.booth,
                "currency": "USD",
                "printAll": False,
                "accountId": creds.account_id,
            },
            headers=headers,
            timeout=20,
        )
        r.raise_for_status()
        barcode_req_id = r.text.strip().strip('"')

    # ── Step 3: Retrieve barcode text ────────────────────────────────────────
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

async def _find_item_id(inv_num: str, db_account_id: int, creds: SandpiperCreds) -> Optional[str]:
    token = await _login(db_account_id, creds)
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"https://app.sandpiperhq.com/api/items/v2/{creds.account_id}/search",
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


async def update_price(inv_num: str, new_price_dollars: float, db_account_id: int) -> bool:
    """Update the asking price of an already-uploaded Sandpiper item.
    Returns True on success, False on failure or missing creds."""
    if not inv_num:
        logger.warning("[sandpiper] update_price called with empty inv_num")
        return False

    creds = load_creds(db_account_id)
    if not creds:
        logger.warning(f"[sandpiper] No creds for account {db_account_id} — skipping price update")
        return False

    token = await _login(db_account_id, creds)
    headers = {"Authorization": f"Bearer {token}"}

    item_id = await _find_item_id(inv_num, db_account_id, creds)
    if not item_id:
        logger.warning(f"[sandpiper] update_price: item not found for inv {inv_num}")
        return False

    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"https://app.sandpiperhq.com/api/items/v2/{creds.account_id}/update",
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
