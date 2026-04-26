"""
main.py
-------
FastAPI server for card-pricer v2 — batch workflow edition.

Routes:
  # Pages
  GET  /                      → redirect to /capture (mobile) or /dashboard (desktop)
  GET  /capture               → mobile PWA capture page
  GET  /dashboard             → desktop review + batch management grid
  GET  /print                 → label print queue

  # Batch API
  POST /api/batch/start       → create new batch
  POST /api/batch/{id}/close  → close batch
  GET  /api/batches           → list all batches

  # Card API
  POST /api/ingest            → upload images, run agent, save card to DB
  GET  /api/cards             → list cards (filter by batch_id, status)
  PATCH /api/cards/{id}       → update card fields (inline edit)
  POST /api/cards/approve     → bulk approve {ids: [...]}

  # Sandpiper batch upload
  POST /api/batch/{id}/upload → upload approved cards to Sandpiper (rate-limited)

  # Labels
  POST /api/labels/generate   → build PDF for selected card ids (in sequence order)
  GET  /api/labels/{filename} → download generated PDF

Run:
  cd card-pricer
  uvicorn main:app --host 0.0.0.0 --port 8001 --reload
"""

import asyncio
import logging
import os
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Request, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

load_dotenv()

from app.agent import run_agent
from app.vision import extract_upc
from app.config import (
    LOCAL_IP, PORT, IOS_SHORTCUT_NAME,
    ENABLE_GENERALIST_MODE, LABEL_FORMAT,
    ENABLE_CATEGORY_PICKER, ENABLE_MAKERS_MARK_SLOT, ENABLE_UPC_SLOT,
    ENABLE_EXTRA_PHOTOS, EXTRA_PHOTO_LIMIT, ENABLE_MOBILE_EDIT, ENABLE_COST_FIELD,
    ENABLE_RANGE_PRICING, DEFAULT_CATEGORY, KNOWN_CATEGORIES,
)
from app.database import (
    init_db, create_batch, close_batch, get_batch, list_batches, get_open_batch,
    insert_card, get_card, list_cards, update_card, approve_cards,
    get_approved_cards, get_uploaded_cards, mark_uploaded, mark_sandpiper_error,
    mark_printed, delete_cards, delete_batch, archive_batch, unarchive_batch,
    prune_empty_batches, duplicate_card,
    get_user_by_email, update_user_login,
    get_account, update_account, list_users, create_user,
    create_invite, get_invite_by_token, list_pending_invites,
    mark_invite_accepted, delete_invite,
)
from app.sandpiper import create_item_and_barcode, update_price as sandpiper_update_price
from app.sheets import append_row
from app import crypto
from app.auth import (
    AuthMiddleware, hash_password, verify_password,
    set_session_cookie, clear_session_cookie,
    make_invite_token, current_user, current_account_id, require_owner,
)

# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("main")

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
# STORAGE_ROOT: writable directory for uploads + labels.
# Unset locally  → files sit inside the repo (current behaviour).
# Set to /data on Railway → persisted on the mounted volume.
STORAGE_ROOT = Path(os.getenv("STORAGE_ROOT", str(BASE_DIR)))
UPLOADS_DIR = STORAGE_ROOT / "uploads"
LABELS_DIR  = STORAGE_ROOT / "labels"
LABEL_SCRIPT = Path(os.getenv(
    "LABEL_SCRIPT_PATH",
    str(BASE_DIR / "label_print" / "make_card_2x2_labels.py")
))
LABEL_SCRIPT_4X3 = Path(os.getenv(
    "LABEL_SCRIPT_4X3_PATH",
    str(BASE_DIR / "label_print" / "make_comic_4x3_labels.py")
))
LABEL_SCRIPT_2X1 = Path(os.getenv(
    "LABEL_SCRIPT_2X1_PATH",
    str(BASE_DIR / "label_print" / "make_antique_2x1_labels.py")
))
LABEL_SCRIPT_1X1 = Path(os.getenv(
    "LABEL_SCRIPT_1X1_PATH",
    str(BASE_DIR / "label_print" / "make_antique_1x1_labels.py")
))

for d in (UPLOADS_DIR, LABELS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(title="Card Pricer v2")

# Auth middleware runs first — every request gets request.state.user / .account_id
# (or is redirected/401'd before reaching a route). Mounted before CORS so that
# unauthenticated cross-origin calls don't get CORS-friendly headers added on top
# of a 401.
app.add_middleware(AuthMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["APP_NAME"] = os.getenv("APP_NAME", "Card Pricer")

# Serve generated labels and uploaded card images as static files
app.mount("/labels",  StaticFiles(directory=str(LABELS_DIR)),  name="labels")
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")

# ─────────────────────────────────────────────────────────────────────────────
# Startup
# ─────────────────────────────────────────────────────────────────────────────

def _seed_first_owner():
    """First-boot seed: if no accounts exist and SEED_OWNER_EMAIL/PASSWORD are set,
    create a default account + owner user. Uses the legacy SANDPIPER_* env vars to
    pre-populate the account's Sandpiper creds (so the existing single-user .env
    keeps working through the multi-tenant transition). After this seed runs once,
    further accounts come from scripts/create_account.py or invites.
    """
    from app.database import list_accounts, create_account, create_user, get_user_by_email

    if list_accounts():
        return  # already seeded

    seed_email = os.getenv("SEED_OWNER_EMAIL")
    seed_password = os.getenv("SEED_OWNER_PASSWORD")
    if not (seed_email and seed_password):
        logger.info("[seed] No accounts and no SEED_OWNER_EMAIL/PASSWORD — skipping seed")
        return

    if get_user_by_email(seed_email):
        logger.warning(f"[seed] User {seed_email} exists but no account — skipping seed")
        return

    sp_username   = os.getenv("SANDPIPER_USERNAME")
    sp_password   = os.getenv("SANDPIPER_PASSWORD")
    sp_account_id = os.getenv("SANDPIPER_ACCOUNT_ID")
    sp_booth      = os.getenv("SANDPIPER_BOOTH")

    encrypted_pw = crypto.encrypt(sp_password) if sp_password else None

    account_id = create_account(
        name=os.getenv("SEED_ACCOUNT_NAME", "Default"),
        sandpiper_username=sp_username,
        sandpiper_password=encrypted_pw,
        sandpiper_account_id=sp_account_id,
        sandpiper_booth=sp_booth,
    )
    user_id = create_user(
        account_id=account_id,
        email=seed_email,
        password_hash=hash_password(seed_password),
        display_name=os.getenv("SEED_OWNER_NAME", seed_email.split("@")[0]),
        role="owner",
    )
    logger.info(f"[seed] Created seed account #{account_id} + owner user #{user_id} ({seed_email})")


@app.on_event("startup")
async def startup():
    init_db()
    _seed_first_owner()
    prune_empty_batches()
    logger.info("Database initialized")


# ─────────────────────────────────────────────────────────────────────────────
# Request models
# ─────────────────────────────────────────────────────────────────────────────

class ApproveRequest(BaseModel):
    ids: list[int]

class UpdateCardRequest(BaseModel):
    fields: dict

class GenerateLabelsRequest(BaseModel):
    ids: list[int]   # card ids, in the order you want them printed

class DeleteCardsRequest(BaseModel):
    ids: list[int]

class UploadCardsRequest(BaseModel):
    ids: list[int]

class StartBatchRequest(BaseModel):
    notes: str = ""
    category: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Page routes
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Redirect to capture (mobile) or dashboard (desktop) based on User-Agent.
    iPhones and Android phones go to /capture.
    iPads, desktops, and everything else go to /dashboard.
    (iPads do NOT include 'mobile' in their UA — they go to dashboard by default,
    but can still navigate to /capture directly to use the camera.)
    """
    ua = request.headers.get("user-agent", "").lower()
    is_phone = any(k in ua for k in ("iphone", "android", "mobile"))
    if is_phone:
        return HTMLResponse(status_code=302, headers={"Location": "/capture"})
    return HTMLResponse(status_code=302, headers={"Location": "/dashboard"})


def _feature_flags(account: dict = None) -> dict:
    """Flag bundle for templates. Per-account settings override global env vars."""
    acct = account or {}
    # enable_cost_field: per-account boolean takes precedence over global env var
    cost_field = bool(acct.get("enable_cost_field")) if "enable_cost_field" in acct else ENABLE_COST_FIELD
    return {
        "generalist_mode": ENABLE_GENERALIST_MODE,
        "category_picker": ENABLE_CATEGORY_PICKER,
        "makers_mark_slot": ENABLE_MAKERS_MARK_SLOT,
        "upc_slot": ENABLE_UPC_SLOT,
        "extra_photos": ENABLE_EXTRA_PHOTOS,
        "extra_photo_limit": EXTRA_PHOTO_LIMIT,
        "mobile_edit": ENABLE_MOBILE_EDIT,
        "cost_field": cost_field,
        "range_pricing": ENABLE_RANGE_PRICING,
        "default_category": DEFAULT_CATEGORY,
        "known_categories": KNOWN_CATEGORIES,
    }


@app.get("/api/config/flags")
async def api_config_flags():
    return _feature_flags()


# ─────────────────────────────────────────────────────────────────────────────
# Auth routes (public — bypass AuthMiddleware via PUBLIC_PATHS)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/", error: Optional[str] = None):
    return templates.TemplateResponse(
        request,
        "login.html",
        {"next": next, "error": error},
    )


@app.post("/login")
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
):
    """Validate credentials → set signed session cookie → redirect to `next`."""
    user = get_user_by_email(email.strip().lower())
    if not user or not verify_password(password, user["password_hash"]):
        # Render login page with error rather than redirect — keeps the entered next path.
        return templates.TemplateResponse(
            request,
            "login.html",
            {"next": next, "error": "Invalid email or password."},
            status_code=401,
        )

    update_user_login(user["id"])
    safe_next = next if next.startswith("/") and not next.startswith("//") else "/"
    response = RedirectResponse(url=safe_next, status_code=302)
    set_session_cookie(response, user["id"])
    logger.info(f"[auth] Login OK — user={user['email']!r} account={user['account_id']}")
    return response


@app.get("/logout")
async def logout(request: Request):
    response = RedirectResponse(url="/login", status_code=302)
    clear_session_cookie(response)
    return response


@app.get("/health")
async def health():
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# Invite accept (public — bypass AuthMiddleware via PUBLIC_PATHS)
# ─────────────────────────────────────────────────────────────────────────────

def _invite_is_valid(invite: Optional[dict]) -> tuple[bool, Optional[str]]:
    """Return (is_valid, reason_if_not). Single source of truth for invite validity."""
    if not invite:
        return False, "Invite not found."
    if invite.get("accepted_at"):
        return False, "This invite has already been used."
    expires_at = invite.get("expires_at")
    if expires_at and expires_at < datetime.utcnow().isoformat(timespec="seconds"):
        return False, "This invite has expired."
    return True, None


@app.get("/invite/accept", response_class=HTMLResponse)
async def invite_accept_page(request: Request, token: str = ""):
    invite = get_invite_by_token(token) if token else None
    valid, reason = _invite_is_valid(invite)
    return templates.TemplateResponse(
        request,
        "invite_accept.html",
        {
            "token": token,
            "invite": invite if valid else None,
            "error": reason,
        },
        status_code=200 if valid else 400,
    )


@app.post("/invite/accept")
async def invite_accept_submit(
    request: Request,
    token: str = Form(...),
    display_name: str = Form(...),
    password: str = Form(...),
):
    invite = get_invite_by_token(token)
    valid, reason = _invite_is_valid(invite)
    if not valid:
        return templates.TemplateResponse(
            request,
            "invite_accept.html",
            {"token": token, "invite": None, "error": reason},
            status_code=400,
        )

    # Email is locked to the invite — invitee can't change it.
    email = invite["email"]
    if get_user_by_email(email):
        # Edge case: someone with the invitee's email signed up between invite
        # creation and acceptance. Bail rather than silently overwrite.
        return templates.TemplateResponse(
            request,
            "invite_accept.html",
            {"token": token, "invite": None,
             "error": "An account with this email already exists. Sign in instead."},
            status_code=400,
        )

    if len(password) < 8:
        return templates.TemplateResponse(
            request,
            "invite_accept.html",
            {"token": token, "invite": invite,
             "error": "Password must be at least 8 characters."},
            status_code=400,
        )

    user_id = create_user(
        account_id=invite["account_id"],
        email=email,
        password_hash=hash_password(password),
        display_name=display_name.strip() or email.split("@")[0],
        role="member",
    )
    mark_invite_accepted(invite["id"])
    update_user_login(user_id)
    logger.info(f"[invite] Accepted — user #{user_id} ({email}) joined account {invite['account_id']}")

    response = RedirectResponse(url="/", status_code=302)
    set_session_cookie(response, user_id)
    return response


# ─────────────────────────────────────────────────────────────────────────────
# Settings (owner-only)
# ─────────────────────────────────────────────────────────────────────────────

class UpdateAccountRequest(BaseModel):
    name: Optional[str] = None
    sandpiper_username: Optional[str] = None
    sandpiper_password: Optional[str] = None  # plaintext from the form; encrypted before storage
    sandpiper_account_id: Optional[str] = None
    sandpiper_booth: Optional[str] = None
    label_format: Optional[str] = None
    enable_cost_field: Optional[bool] = None


class CreateInviteRequest(BaseModel):
    email: str


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    require_owner(request)
    account_id = current_account_id(request)
    user = current_user(request)
    account = get_account(account_id) or {}
    members = list_users(account_id)
    invites = list_pending_invites(account_id)
    # Strip the encrypted Sandpiper password before passing to the template —
    # the form will show "(unchanged)" placeholder, never the ciphertext.
    safe_account = {k: v for k, v in account.items() if k != "sandpiper_password"}
    safe_account["sandpiper_password_set"] = bool(account.get("sandpiper_password"))
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "user": user,
            "account": safe_account,
            "members": members,
            "invites": invites,
        },
    )


@app.post("/api/settings/account")
async def api_settings_update_account(request: Request, body: UpdateAccountRequest):
    """Update the current account's name + Sandpiper creds. Owner-only.

    Sandpiper password: empty/None means 'leave unchanged'. The plaintext is
    encrypted before being written.
    """
    require_owner(request)
    account_id = current_account_id(request)

    fields: dict = {}
    if body.name is not None:
        fields["name"] = body.name.strip()
    if body.sandpiper_username is not None:
        fields["sandpiper_username"] = body.sandpiper_username.strip()
    if body.sandpiper_account_id is not None:
        fields["sandpiper_account_id"] = body.sandpiper_account_id.strip()
    if body.sandpiper_booth is not None:
        fields["sandpiper_booth"] = body.sandpiper_booth.strip()
    if body.sandpiper_password:
        # Only update password when a new one is provided. Empty string ⇒ keep current.
        fields["sandpiper_password"] = crypto.encrypt(body.sandpiper_password)
    if body.label_format is not None:
        valid_formats = {"auto", "card_2x2", "antique_4x3", "antique_2x1", "antique_1x1"}
        fields["label_format"] = body.label_format if body.label_format in valid_formats else "auto"
    if body.enable_cost_field is not None:
        fields["enable_cost_field"] = body.enable_cost_field

    if not fields:
        return {"ok": True, "updated": 0}

    update_account(account_id, fields)
    logger.info(f"[settings] Updated account {account_id}: keys={sorted(fields.keys())}")
    return {"ok": True, "updated": len(fields)}


@app.post("/api/settings/invites")
async def api_settings_create_invite(request: Request, body: CreateInviteRequest):
    """Owner creates an invite. Returns the URL — owner copies + texts it."""
    require_owner(request)
    account_id = current_account_id(request)
    user = current_user(request)

    email = body.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(400, "Invalid email")
    if get_user_by_email(email):
        raise HTTPException(400, "A user with that email already exists")

    token = make_invite_token()
    # 7-day expiry — keep ISO so it sorts/compares lexicographically with _now().
    from datetime import timedelta
    expires_at = (datetime.utcnow() + timedelta(days=7)).isoformat(timespec="seconds")
    invite_id = create_invite(
        account_id=account_id, email=email, token=token,
        invited_by=user["id"], expires_at=expires_at,
    )

    # Build the invite URL using the request's host so it works on both local + prod.
    base = str(request.base_url).rstrip("/")
    invite_url = f"{base}/invite/accept?token={token}"
    logger.info(f"[settings] Created invite #{invite_id} for {email} (account {account_id})")
    return {"ok": True, "invite_id": invite_id, "url": invite_url, "expires_at": expires_at}


@app.post("/api/settings/invites/{invite_id}/delete")
async def api_settings_delete_invite(request: Request, invite_id: int):
    require_owner(request)
    account_id = current_account_id(request)
    delete_invite(invite_id, account_id)
    return {"ok": True}


@app.get("/capture", response_class=HTMLResponse)
async def capture_page(request: Request):
    account_id = current_account_id(request)
    user = current_user(request)
    account = get_account(account_id) or {}
    open_batch = get_open_batch(account_id=account_id)
    return templates.TemplateResponse(
        request,
        "mobile/capture.html",
        {
            "open_batch": open_batch,
            "flags": _feature_flags(account),
            "user": user,
        },
    )


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    account_id = current_account_id(request)
    user = current_user(request)
    account = get_account(account_id) or {}
    batches = list_batches(account_id=account_id)
    return templates.TemplateResponse(
        request,
        "desktop/dashboard.html",
        {
            "batches": batches,
            "flags": _feature_flags(account),
            "user": user,
        },
    )


@app.get("/print", response_class=HTMLResponse)
async def print_page(request: Request):
    user = current_user(request)
    return templates.TemplateResponse(
        request,
        "desktop/print.html",
        {"user": user},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Batch API
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/batch/start")
async def api_batch_start(request: Request, body: Optional[StartBatchRequest] = None):
    """Create a new open batch. Auto-names by date/time. Optional notes + category."""
    account_id = current_account_id(request)
    user = current_user(request)
    notes = body.notes if body else ""
    category = (body.category if body else None) or None
    if category and ENABLE_GENERALIST_MODE:
        category = category.lower()
        if category not in KNOWN_CATEGORIES:
            category = "other"
    elif not ENABLE_GENERALIST_MODE:
        category = None  # ignore category when generalist mode is off

    name = f"Batch {datetime.now().strftime('%b %d %Y %I:%M %p')}"
    batch_id = create_batch(
        name, notes, category=category,
        account_id=account_id, created_by_user_id=user["id"],
    )
    logger.info(
        f"[batch] Started batch #{batch_id}: {name!r} (account {account_id}, user {user['id']})"
        + (f" notes={notes!r}" if notes else "")
        + (f" category={category!r}" if category else "")
    )
    return {"batch_id": batch_id, "name": name, "notes": notes, "category": category}


@app.post("/api/batch/{batch_id}/archive")
async def api_batch_archive(request: Request, batch_id: int):
    """Archive a batch and set all its cards to archived status."""
    account_id = current_account_id(request)
    batch = get_batch(batch_id, account_id=account_id)
    if not batch:
        raise HTTPException(404, "Batch not found")
    archive_batch(batch_id, account_id=account_id)
    logger.info(f"[batch] Archived batch #{batch_id} (account {account_id})")
    return {"ok": True}


@app.post("/api/batch/{batch_id}/unarchive")
async def api_batch_unarchive(request: Request, batch_id: int):
    """Restore an archived batch — sets cards back to printed status."""
    account_id = current_account_id(request)
    batch = get_batch(batch_id, account_id=account_id)
    if not batch:
        raise HTTPException(404, "Batch not found")
    unarchive_batch(batch_id, account_id=account_id)
    logger.info(f"[batch] Unarchived batch #{batch_id} (account {account_id})")
    return {"ok": True}


@app.post("/api/batch/{batch_id}/delete")
async def api_batch_delete(request: Request, batch_id: int):
    """Hard-delete a batch and all its cards. Sandpiper entries become orphans."""
    account_id = current_account_id(request)
    batch = get_batch(batch_id, account_id=account_id)
    if not batch:
        raise HTTPException(404, "Batch not found")
    delete_batch(batch_id, account_id=account_id)
    logger.info(f"[batch] Deleted batch #{batch_id} (account {account_id})")
    return {"ok": True}


@app.post("/api/batch/{batch_id}/close")
async def api_batch_close(request: Request, batch_id: int):
    account_id = current_account_id(request)
    batch = get_batch(batch_id, account_id=account_id)
    if not batch:
        raise HTTPException(404, "Batch not found")
    close_batch(batch_id)
    logger.info(f"[batch] Closed batch #{batch_id} (account {account_id})")
    return {"ok": True}


@app.get("/api/batches")
async def api_list_batches(request: Request, include_archived: bool = False):
    account_id = current_account_id(request)
    return list_batches(include_archived=include_archived, account_id=account_id)


@app.get("/api/batch/{batch_id}")
async def api_get_batch(request: Request, batch_id: int):
    account_id = current_account_id(request)
    batch = get_batch(batch_id, account_id=account_id)
    if not batch:
        raise HTTPException(404, "Batch not found")
    cards = list_cards(batch_id=batch_id, account_id=account_id)
    return {"batch": batch, "cards": cards}


# ─────────────────────────────────────────────────────────────────────────────
# Card capture (mobile)
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/ingest")
async def api_ingest(
    request: Request,
    files: list[UploadFile] = File(...),
    category: Optional[str] = Form(None),
    cost: Optional[float] = Form(None),
    makers_mark: Optional[UploadFile] = File(None),
    upc_image: Optional[UploadFile] = File(None),
):
    """
    Receive 1–N item images, run the pricing agent, save card to DB.
    Requires an open batch — returns 400 if none exists.

    Optional form fields (all flag-gated):
      category    — overrides the batch's default category for this item
      makers_mark — extra photo of a maker's mark / signature (non-card items)
      upc_image   — photo of a UPC barcode; AI extracts the digits for precise eBay lookup
    """
    account_id = current_account_id(request)
    open_batch = get_open_batch(account_id=account_id)
    if not open_batch:
        raise HTTPException(
            400,
            "No open batch. Start a batch first before uploading cards."
        )

    batch_id = open_batch["id"]

    # Resolve effective category: per-item > batch > default
    if ENABLE_GENERALIST_MODE:
        effective_category = (
            (category or "").lower().strip()
            or (open_batch.get("category") or "").lower().strip()
            or DEFAULT_CATEGORY
        )
        if effective_category not in KNOWN_CATEGORIES:
            effective_category = "other"
    else:
        effective_category = "card"

    logger.info(
        f"[ingest] {len(files)} image(s) → batch #{batch_id} | category={effective_category}"
    )

    # Read images
    image_bytes_list = []
    image_paths = []
    for f in files:
        data = await f.read()
        image_bytes_list.append(data)
        ext = Path(f.filename or "card.jpg").suffix or ".jpg"
        filename = f"{uuid.uuid4().hex[:8]}{ext}"
        img_path = UPLOADS_DIR / filename
        img_path.write_bytes(data)
        image_paths.append(str(img_path))

    # Optional maker's-mark image — stored separately, not sent to vision
    makers_mark_path = None
    if ENABLE_MAKERS_MARK_SLOT and makers_mark is not None:
        mm_data = await makers_mark.read()
        if mm_data:
            ext = Path(makers_mark.filename or "mark.jpg").suffix or ".jpg"
            fn = f"{uuid.uuid4().hex[:8]}_mark{ext}"
            mm_path = UPLOADS_DIR / fn
            mm_path.write_bytes(mm_data)
            makers_mark_path = str(mm_path)

    # Optional UPC image — extract digits via AI for precise eBay lookup
    upc = None
    if ENABLE_UPC_SLOT and upc_image is not None:
        upc_data = await upc_image.read()
        if upc_data:
            upc = await extract_upc(upc_data)
            if upc:
                logger.info(f"[ingest] UPC extracted: {upc}")

    # Run agent (vision → pricing → valuation)
    batch_notes = open_batch.get("notes", "")
    result = await run_agent(
        image_bytes_list,
        batch_notes=batch_notes,
        category=effective_category,
        upc=upc,
    )
    result["image_path"] = ",".join(image_paths)
    if makers_mark_path:
        result["makers_mark_image_path"] = makers_mark_path
    if cost is not None:
        result["cost"] = cost

    # Save to database
    card_id = insert_card(batch_id, result)

    card = get_card(card_id, account_id=account_id)
    logger.info(
        f"[ingest] Card #{card_id} saved — "
        f"{result.get('display_title') or result.get('title')!r} → ${result.get('price')}"
    )

    return {
        "ok": True,
        "card_id": card_id,
        "title": result.get("display_title") or result.get("title"),
        "price": result.get("price"),
        "ai_price_low": result.get("ai_price_low"),
        "ai_price_high": result.get("ai_price_high"),
        "ai_price_confidence": result.get("ai_price_confidence"),
        "upc": upc,
        "batch_id": batch_id,
        "sequence_num": card["sequence_num"] if card else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Card API (desktop)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/cards")
async def api_list_cards(
    request: Request,
    batch_id: Optional[int] = None,
    status: Optional[str] = None,
    exclude_archived: bool = False,
):
    account_id = current_account_id(request)
    return list_cards(
        batch_id=batch_id, status=status,
        exclude_archived=exclude_archived, account_id=account_id,
    )


@app.get("/api/cards/{card_id}")
async def api_get_card(request: Request, card_id: int):
    account_id = current_account_id(request)
    card = get_card(card_id, account_id=account_id)
    if not card:
        raise HTTPException(404, "Card not found")
    return card


@app.patch("/api/cards/{card_id}")
async def api_update_card(request: Request, card_id: int, body: UpdateCardRequest):
    """Inline edit — update any card fields from the desktop grid.

    If final_price changes on an already-uploaded card, push the new price
    to Sandpiper so the POS stays in sync with the dashboard.
    """
    account_id = current_account_id(request)
    before = get_card(card_id, account_id=account_id)
    if not before:
        raise HTTPException(404, "Card not found")

    update_card(card_id, body.fields, account_id=account_id)

    new_price = body.fields.get("final_price")
    old_price = before.get("final_price")
    price_changed = (
        new_price is not None
        and old_price is not None
        and float(new_price) != float(old_price)
    )
    was_uploaded = before.get("status") in ("uploaded", "printed", "archived")
    inv_num = before.get("inventory_number")

    if price_changed and was_uploaded and inv_num:
        try:
            ok = await sandpiper_update_price(inv_num, float(new_price), account_id)
            if not ok:
                logger.warning(f"[patch] Sandpiper price-sync failed for card #{card_id}")
        except Exception as e:
            logger.error(f"[patch] Sandpiper price-sync error for card #{card_id}: {e}")

    return {"ok": True}


@app.post("/api/cards/{card_id}/duplicate")
async def api_duplicate_card(request: Request, card_id: int):
    """
    Copy a card (same data, new inv#, seq#, pending status, no barcode).
    Used on mobile when you have 2+ identical cards in a stack.
    """
    account_id = current_account_id(request)
    new_id = duplicate_card(card_id, account_id=account_id)
    if not new_id:
        raise HTTPException(404, "Card not found")
    card = get_card(new_id, account_id=account_id)
    logger.info(f"[duplicate] Card #{card_id} → new card #{new_id} (inv #{card['inventory_number']})")
    return {"ok": True, "card_id": new_id, "inventory_number": card["inventory_number"],
            "sequence_num": card["sequence_num"]}


@app.post("/api/cards/approve")
async def api_approve_cards(request: Request, body: ApproveRequest):
    """Bulk approve selected cards (pending → approved)."""
    account_id = current_account_id(request)
    approve_cards(body.ids, account_id=account_id)
    logger.info(f"[approve] Approved {len(body.ids)} cards (account {account_id})")
    return {"ok": True, "approved": len(body.ids)}


@app.post("/api/cards/delete")
async def api_delete_cards(request: Request, body: DeleteCardsRequest):
    """
    Hard-delete cards by id. Works regardless of status.
    If the card was already uploaded to Sandpiper, it becomes an orphan there
    — that's intentional, the user will handle it manually.
    """
    account_id = current_account_id(request)
    if not body.ids:
        raise HTTPException(400, "No card ids provided")
    delete_cards(body.ids, account_id=account_id)
    logger.info(f"[delete] Deleted {len(body.ids)} cards (account {account_id}): {body.ids}")
    return {"ok": True, "deleted": len(body.ids)}


# ─────────────────────────────────────────────────────────────────────────────
# Sandpiper upload — works on a list of card IDs (no "approved" step needed)
# ─────────────────────────────────────────────────────────────────────────────

SANDPIPER_DELAY = 1.5   # seconds between API calls — be kind to their server


async def _upload_cards_to_sandpiper(cards: list[dict], account_id: int) -> dict:
    """
    Core upload logic — shared by both the ID-based and batch-based endpoints.
    - 1.5s pause between each card
    - Skips cards that already have a barcode
    - On error: logs it, marks the card, moves on (no retry loops)
    Uses the supplied account_id to load the right Sandpiper credentials.
    """
    uploaded = 0
    errors = 0

    for i, card in enumerate(cards):
        card_id = card["id"]

        if card.get("barcode"):
            logger.info(f"[upload] Card #{card_id} already has barcode — skipping")
            continue

        inv_num = card.get("inventory_number") or f"CRD-{card_id}"
        title   = card.get("display_title") or card.get("card_name") or "Card"
        price   = float(card.get("final_price") or 0)
        cost    = float(card.get("cost") or 0)

        logger.info(f"[upload] Card #{card_id} ({i+1}/{len(cards)}): {title!r} @ ${price}")

        try:
            barcode = await create_item_and_barcode(inv_num, title, price, account_id, cost_dollars=cost)
            if barcode and barcode != "#":
                mark_uploaded(card_id, inv_num, barcode)
                try:
                    await append_row(_build_sheets_row(card, inv_num, barcode))
                except Exception as e:
                    logger.warning(f"[upload] Sheets append failed for card #{card_id}: {e}")
                uploaded += 1
                logger.info(f"[upload] ✓ Card #{card_id} → barcode {barcode}")
            else:
                mark_sandpiper_error(card_id, "No barcode returned")
                errors += 1
                logger.warning(f"[upload] ✗ Card #{card_id} — no barcode returned")
        except Exception as e:
            mark_sandpiper_error(card_id, str(e))
            errors += 1
            logger.error(f"[upload] ✗ Card #{card_id} error: {e}")

        if i < len(cards) - 1:
            await asyncio.sleep(SANDPIPER_DELAY)

    return {"ok": True, "uploaded": uploaded, "errors": errors, "total": len(cards)}


@app.post("/api/cards/upload")
async def api_upload_cards(request: Request, body: UploadCardsRequest):
    """
    Upload specific selected cards to Sandpiper (by ID).
    Replaces the old approve→upload two-step — cards go directly from pending to uploaded.
    """
    account_id = current_account_id(request)
    if not body.ids:
        raise HTTPException(400, "No card ids provided")
    cards = [c for cid in body.ids if (c := get_card(cid, account_id=account_id))]
    if not cards:
        raise HTTPException(404, "None of the specified cards exist")
    logger.info(f"[upload] Uploading {len(cards)} selected cards to Sandpiper (account {account_id})")
    result = await _upload_cards_to_sandpiper(cards, account_id)
    logger.info(f"[upload] Done — {result['uploaded']} uploaded, {result['errors']} errors")
    return result


@app.post("/api/batch/{batch_id}/upload")
async def api_batch_upload(request: Request, batch_id: int):
    """
    Upload all pending cards in a batch to Sandpiper (batch-level convenience endpoint).
    """
    account_id = current_account_id(request)
    batch = get_batch(batch_id, account_id=account_id)
    if not batch:
        raise HTTPException(404, "Batch not found")

    cards = list_cards(batch_id=batch_id, status="pending", account_id=account_id)
    if not cards:
        return {"ok": True, "message": "No pending cards to upload", "uploaded": 0, "errors": 0}

    logger.info(f"[upload] Starting Sandpiper upload for batch #{batch_id} — {len(cards)} cards (account {account_id})")
    result = await _upload_cards_to_sandpiper(cards, account_id)
    logger.info(f"[upload] Batch #{batch_id} complete — {result['uploaded']} uploaded, {result['errors']} errors")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Label generation
# ─────────────────────────────────────────────────────────────────────────────

def pick_label_script(card: dict, account: dict = None) -> tuple[Path, str]:
    """
    Choose the label script + format for a given card.
    Returns (script_path, format_key) where format_key ∈ {"card_2x2", "antique_4x3", "antique_2x1", "antique_1x1"}.

    Priority: account.label_format > LABEL_FORMAT env var > auto
      auto         — card category → 2x2, everything else → 4x3
      card_2x2     — 2"×2" trading card label
      antique_4x3  — 4"×3" antique/comic label
      antique_2x1  — 2"×1" compact antique label
    """
    fmt = ((account or {}).get("label_format") or LABEL_FORMAT or "auto").lower()
    if fmt == "card_2x2":
        return LABEL_SCRIPT, "card_2x2"
    if fmt == "antique_4x3":
        return LABEL_SCRIPT_4X3, "antique_4x3"
    if fmt == "antique_2x1":
        return LABEL_SCRIPT_2X1, "antique_2x1"
    if fmt == "antique_1x1":
        return LABEL_SCRIPT_1X1, "antique_1x1"
    # auto
    category = (card.get("category") or "card").lower()
    if ENABLE_GENERALIST_MODE and category != "card":
        return LABEL_SCRIPT_4X3, "antique_4x3"
    return LABEL_SCRIPT, "card_2x2"


def _write_label_input(
    cards: list[dict],
    format_key: str,
    input_file: Path,
    account: dict = None,
) -> None:
    """Write the TSV input file matching the chosen label script's column contract."""
    booth = (account or {}).get("sandpiper_booth") or ""
    with open(input_file, "w", encoding="utf-8") as f:
        for card in cards:
            price = card.get("final_price") or 0
            if format_key == "antique_4x3":
                # 8 cols: Title, Bullet1, Bullet2, Bullet3, Publisher, Price, InventoryID, Barcode
                publisher = card.get("maker") or card.get("publisher_brand") or ""
                row = "\t".join([
                    card.get("display_title") or card.get("card_name") or "",
                    card.get("bullet_1") or "",
                    card.get("bullet_2") or "",
                    card.get("bullet_3") or "",
                    publisher,
                    f"${price:.2f}",
                    card.get("inventory_number") or "",
                    card.get("barcode") or "",
                ])
            elif format_key == "antique_2x1":
                # 5 cols: Title, Price, InventoryID, Barcode, Booth
                row = "\t".join([
                    card.get("display_title") or card.get("card_name") or "",
                    f"${price:.2f}",
                    card.get("inventory_number") or "",
                    card.get("barcode") or "",
                    booth,
                ])
            elif format_key == "antique_1x1":
                # 4 cols: Title, Price, InventoryID, Barcode
                row = "\t".join([
                    card.get("display_title") or card.get("card_name") or "",
                    f"${price:.2f}",
                    card.get("inventory_number") or "",
                    card.get("barcode") or "",
                ])
            else:
                # card_2x2 — 7 cols: title, bullet_1, bullet_2, price_source, price, inv, barcode
                row = "\t".join([
                    card.get("display_title") or card.get("card_name") or "",
                    card.get("bullet_1") or "",
                    card.get("bullet_2") or "",
                    card.get("price_source") or "",
                    f"${price:.2f}",
                    card.get("inventory_number") or "",
                    card.get("barcode") or "",
                ])
            f.write(row + "\n")


@app.post("/api/labels/generate")
async def api_generate_labels(request: Request, body: GenerateLabelsRequest):
    """
    Generate a label PDF for selected card ids (in the order provided).
    Script + format picked per the first card's category (all cards in one call
    should share a format — mixed calls fall back to the first card's choice).
    """
    account_id = current_account_id(request)
    if not body.ids:
        raise HTTPException(400, "No card ids provided")

    # Fetch cards in the requested order, scoped to this account
    cards = []
    for cid in body.ids:
        card = get_card(cid, account_id=account_id)
        if card and card.get("barcode"):
            cards.append(card)
        else:
            logger.warning(f"[labels] Card #{cid} skipped — no barcode yet")

    if not cards:
        raise HTTPException(400, "None of the selected cards have barcodes yet")

    account = get_account(account_id)
    script_path, format_key = pick_label_script(cards[0], account=account)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    input_file = LABELS_DIR / f"label_input_{ts}.txt"
    output_pdf = LABELS_DIR / f"labels_{ts}.pdf"

    _write_label_input(cards, format_key, input_file, account=account)

    if not script_path.exists():
        raise HTTPException(
            500,
            f"Label script not found at {script_path}. "
            f"Set LABEL_SCRIPT_PATH / LABEL_SCRIPT_4X3_PATH in .env."
        )

    # Use run_in_executor + subprocess.run — asyncio.create_subprocess_exec
    # raises NotImplementedError on Windows with SelectorEventLoop (uvicorn default)
    def _run_script():
        return subprocess.run(
            [sys.executable, str(script_path), str(input_file), str(output_pdf)],
            capture_output=True, text=True,
        )

    loop = asyncio.get_event_loop()
    proc_result = await loop.run_in_executor(None, _run_script)

    if proc_result.returncode != 0:
        logger.error(f"[labels] Script failed: {proc_result.stderr}")
        raise HTTPException(500, f"Label generation failed: {proc_result.stderr[:200]}")

    logger.info(f"[labels] Generated {len(cards)} labels → {output_pdf.name}")

    # Mark cards as printed
    mark_printed(body.ids)

    # Clean up input file
    input_file.unlink(missing_ok=True)

    return {
        "ok": True,
        "filename": output_pdf.name,
        "count": len(cards),
        "url": f"/labels/{output_pdf.name}",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _build_sheets_row(card: dict, inv_num: str, barcode: str) -> dict:
    price = card.get("final_price") or 0
    return {
        "Title": card.get("display_title") or card.get("card_name") or "",
        "Bullet 1": card.get("bullet_1") or "",
        "Bullet 2": card.get("bullet_2") or "",
        "Price Source": card.get("price_source") or "",
        "Price": f"${price:.2f}",
        "Inventory #": inv_num,
        "Barcode": barcode,
        "Condition": card.get("condition") or "",
        "Base_Price": card.get("base_price") or "",
        "AI Notes": card.get("ai_notes") or "",
    }


