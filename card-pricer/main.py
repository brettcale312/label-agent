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
from fastapi import FastAPI, File, Request, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

load_dotenv()

from app.agent import run_agent
from app.config import LOCAL_IP, PORT, IOS_SHORTCUT_NAME
from app.database import (
    init_db, create_batch, close_batch, get_batch, list_batches, get_open_batch,
    insert_card, get_card, list_cards, update_card, approve_cards,
    get_approved_cards, get_uploaded_cards, mark_uploaded, mark_sandpiper_error,
    mark_printed, delete_cards, delete_batch, archive_batch, unarchive_batch,
    prune_empty_batches, duplicate_card,
)
from app.sandpiper import create_item_and_barcode
from app.sheets import append_row

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
UPLOADS_DIR = BASE_DIR / "uploads"
LABELS_DIR = BASE_DIR / "labels"
LABEL_SCRIPT = Path(os.getenv(
    "LABEL_SCRIPT_PATH",
    r"C:\dev\python\label_tools\2x2_TradingCard_Labels\make_card_2x2_labels.py"
))

for d in (UPLOADS_DIR, LABELS_DIR):
    d.mkdir(exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(title="Card Pricer v2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Serve generated labels and uploaded card images as static files
app.mount("/labels",  StaticFiles(directory=str(LABELS_DIR)),  name="labels")
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")

# ─────────────────────────────────────────────────────────────────────────────
# Startup
# ─────────────────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    init_db()
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

class StartBatchRequest(BaseModel):
    notes: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Page routes
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Redirect to capture (mobile) or dashboard (desktop) based on User-Agent."""
    ua = request.headers.get("user-agent", "").lower()
    is_mobile = any(k in ua for k in ("iphone", "android", "mobile"))
    if is_mobile:
        return HTMLResponse(status_code=302, headers={"Location": "/capture"})
    return HTMLResponse(status_code=302, headers={"Location": "/dashboard"})


@app.get("/capture", response_class=HTMLResponse)
async def capture_page(request: Request):
    open_batch = get_open_batch()
    return templates.TemplateResponse(
        "mobile/capture.html",
        {"request": request, "open_batch": open_batch},
    )


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    batches = list_batches()
    return templates.TemplateResponse(
        "desktop/dashboard.html",
        {"request": request, "batches": batches},
    )


@app.get("/print", response_class=HTMLResponse)
async def print_page(request: Request):
    return templates.TemplateResponse(
        "desktop/print.html",
        {"request": request},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Batch API
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/batch/start")
async def api_batch_start(body: Optional[StartBatchRequest] = None):
    """Create a new open batch. Auto-names by date/time. Optional notes for context."""
    notes = body.notes if body else ""
    name = f"Batch {datetime.now().strftime('%b %d %Y %I:%M %p')}"
    batch_id = create_batch(name, notes)
    logger.info(f"[batch] Started batch #{batch_id}: {name!r}" + (f" notes={notes!r}" if notes else ""))
    return {"batch_id": batch_id, "name": name, "notes": notes}


@app.post("/api/batch/{batch_id}/archive")
async def api_batch_archive(batch_id: int):
    """Archive a batch and set all its cards to archived status."""
    batch = get_batch(batch_id)
    if not batch:
        raise HTTPException(404, "Batch not found")
    archive_batch(batch_id)
    logger.info(f"[batch] Archived batch #{batch_id}")
    return {"ok": True}


@app.post("/api/batch/{batch_id}/unarchive")
async def api_batch_unarchive(batch_id: int):
    """Restore an archived batch — sets cards back to printed status."""
    batch = get_batch(batch_id)
    if not batch:
        raise HTTPException(404, "Batch not found")
    unarchive_batch(batch_id)
    logger.info(f"[batch] Unarchived batch #{batch_id}")
    return {"ok": True}


@app.post("/api/batch/{batch_id}/delete")
async def api_batch_delete(batch_id: int):
    """Hard-delete a batch and all its cards. Sandpiper entries become orphans."""
    batch = get_batch(batch_id)
    if not batch:
        raise HTTPException(404, "Batch not found")
    delete_batch(batch_id)
    logger.info(f"[batch] Deleted batch #{batch_id}")
    return {"ok": True}


@app.post("/api/batch/{batch_id}/close")
async def api_batch_close(batch_id: int):
    batch = get_batch(batch_id)
    if not batch:
        raise HTTPException(404, "Batch not found")
    close_batch(batch_id)
    logger.info(f"[batch] Closed batch #{batch_id}")
    return {"ok": True}


@app.get("/api/batches")
async def api_list_batches(include_archived: bool = False):
    return list_batches(include_archived=include_archived)


@app.get("/api/batch/{batch_id}")
async def api_get_batch(batch_id: int):
    batch = get_batch(batch_id)
    if not batch:
        raise HTTPException(404, "Batch not found")
    cards = list_cards(batch_id=batch_id)
    return {"batch": batch, "cards": cards}


# ─────────────────────────────────────────────────────────────────────────────
# Card capture (mobile)
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/ingest")
async def api_ingest(files: list[UploadFile] = File(...)):
    """
    Receive 1–3 card images, run the pricing agent, save card to DB.
    Requires an open batch — returns 400 if none exists.
    """
    open_batch = get_open_batch()
    if not open_batch:
        raise HTTPException(
            400,
            "No open batch. Start a batch first before uploading cards."
        )

    batch_id = open_batch["id"]
    logger.info(f"[ingest] {len(files)} image(s) → batch #{batch_id}")

    # Read images
    image_bytes_list = []
    image_paths = []
    for f in files:
        data = await f.read()
        image_bytes_list.append(data)
        # Save image to disk
        ext = Path(f.filename or "card.jpg").suffix or ".jpg"
        filename = f"{uuid.uuid4().hex[:8]}{ext}"
        img_path = UPLOADS_DIR / filename
        img_path.write_bytes(data)
        image_paths.append(str(img_path))

    # Run agent (vision → pricing → valuation)
    # Pass batch notes as context so the vision model knows what kind of cards these are
    batch_notes = open_batch.get("notes", "")
    result = await run_agent(image_bytes_list, batch_notes=batch_notes)
    result["image_path"] = ",".join(image_paths)

    # Save to database
    card_id = insert_card(batch_id, result)

    card = get_card(card_id)
    logger.info(
        f"[ingest] Card #{card_id} saved — "
        f"{result.get('display_title') or result.get('title')!r} → ${result.get('price')}"
    )

    return {
        "ok": True,
        "card_id": card_id,
        "title": result.get("display_title") or result.get("title"),
        "price": result.get("price"),
        "batch_id": batch_id,
        "sequence_num": card["sequence_num"] if card else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Card API (desktop)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/cards")
async def api_list_cards(
    batch_id: Optional[int] = None,
    status: Optional[str] = None,
    exclude_archived: bool = False,
):
    return list_cards(batch_id=batch_id, status=status, exclude_archived=exclude_archived)


@app.get("/api/cards/{card_id}")
async def api_get_card(card_id: int):
    card = get_card(card_id)
    if not card:
        raise HTTPException(404, "Card not found")
    return card


@app.patch("/api/cards/{card_id}")
async def api_update_card(card_id: int, body: UpdateCardRequest):
    """Inline edit — update any card fields from the desktop grid."""
    if not get_card(card_id):
        raise HTTPException(404, "Card not found")
    update_card(card_id, body.fields)
    return {"ok": True}


@app.post("/api/cards/{card_id}/duplicate")
async def api_duplicate_card(card_id: int):
    """
    Copy a card (same data, new inv#, seq#, pending status, no barcode).
    Used on mobile when you have 2+ identical cards in a stack.
    """
    new_id = duplicate_card(card_id)
    if not new_id:
        raise HTTPException(404, "Card not found")
    card = get_card(new_id)
    logger.info(f"[duplicate] Card #{card_id} → new card #{new_id} (inv #{card['inventory_number']})")
    return {"ok": True, "card_id": new_id, "inventory_number": card["inventory_number"],
            "sequence_num": card["sequence_num"]}


@app.post("/api/cards/approve")
async def api_approve_cards(body: ApproveRequest):
    """Bulk approve selected cards (pending → approved)."""
    approve_cards(body.ids)
    logger.info(f"[approve] Approved {len(body.ids)} cards")
    return {"ok": True, "approved": len(body.ids)}


@app.post("/api/cards/delete")
async def api_delete_cards(body: DeleteCardsRequest):
    """
    Hard-delete cards by id. Works regardless of status.
    If the card was already uploaded to Sandpiper, it becomes an orphan there
    — that's intentional, the user will handle it manually.
    """
    if not body.ids:
        raise HTTPException(400, "No card ids provided")
    delete_cards(body.ids)
    logger.info(f"[delete] Deleted {len(body.ids)} cards: {body.ids}")
    return {"ok": True, "deleted": len(body.ids)}


# ─────────────────────────────────────────────────────────────────────────────
# Sandpiper batch upload (rate-limited)
# ─────────────────────────────────────────────────────────────────────────────

SANDPIPER_DELAY = 1.5   # seconds between API calls — be kind to their server

@app.post("/api/batch/{batch_id}/upload")
async def api_batch_upload(batch_id: int):
    """
    Upload all approved cards in a batch to Sandpiper.
    - 1.5s pause between each card
    - Skips cards that already have a barcode
    - On error: logs it, marks the card, moves on (no retry loops)
    """
    batch = get_batch(batch_id)
    if not batch:
        raise HTTPException(404, "Batch not found")

    cards = get_approved_cards(batch_id)
    if not cards:
        return {"ok": True, "message": "No approved cards to upload", "uploaded": 0, "errors": 0}

    uploaded = 0
    errors = 0

    logger.info(f"[upload] Starting Sandpiper upload for batch #{batch_id} — {len(cards)} cards")

    for i, card in enumerate(cards):
        card_id = card["id"]

        # Safety: skip if already has a barcode (never double-upload)
        if card.get("barcode"):
            logger.info(f"[upload] Card #{card_id} already has barcode — skipping")
            continue

        # Inventory number was assigned at ingest time — use what's in the DB
        inv_num = card.get("inventory_number") or f"CRD-{card_id}"

        title = card.get("display_title") or card.get("card_name") or "Card"
        price = float(card.get("final_price") or 0)

        logger.info(
            f"[upload] Card #{card_id} ({i+1}/{len(cards)}): {title!r} @ ${price}"
        )

        try:
            barcode = await create_item_and_barcode(inv_num, title, price)
            if barcode and barcode != "#":
                mark_uploaded(card_id, inv_num, barcode)
                # Also append to Google Sheets
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

        # Rate limiting — pause between calls (except after the last one)
        if i < len(cards) - 1:
            await asyncio.sleep(SANDPIPER_DELAY)

    logger.info(f"[upload] Batch #{batch_id} complete — {uploaded} uploaded, {errors} errors")
    return {
        "ok": True,
        "uploaded": uploaded,
        "errors": errors,
        "total": len(cards),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Label generation
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/labels/generate")
async def api_generate_labels(body: GenerateLabelsRequest):
    """
    Generate a 2x2 PDF for selected card ids (in the order provided).
    Calls the existing make_card_2x2_labels.py script.
    Returns the filename of the generated PDF.
    """
    if not body.ids:
        raise HTTPException(400, "No card ids provided")

    # Fetch cards in the requested order
    cards = []
    for cid in body.ids:
        card = get_card(cid)
        if card and card.get("barcode"):
            cards.append(card)
        else:
            logger.warning(f"[labels] Card #{cid} skipped — no barcode yet")

    if not cards:
        raise HTTPException(400, "None of the selected cards have barcodes yet")

    # Build tab-separated input file
    # Columns: title, bullet_1, bullet_2, price_source, final_price, inventory_number, barcode
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    input_file = LABELS_DIR / f"label_input_{ts}.txt"
    output_pdf = LABELS_DIR / f"labels_{ts}.pdf"

    with open(input_file, "w", encoding="utf-8") as f:
        for card in cards:
            price = card.get("final_price") or 0
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

    # Run the label script
    if not LABEL_SCRIPT.exists():
        raise HTTPException(
            500,
            f"Label script not found at {LABEL_SCRIPT}. "
            "Set LABEL_SCRIPT_PATH in .env to point to make_card_2x2_labels.py"
        )

    # Use run_in_executor + subprocess.run — asyncio.create_subprocess_exec
    # raises NotImplementedError on Windows with SelectorEventLoop (uvicorn default)
    def _run_script():
        return subprocess.run(
            [sys.executable, str(LABEL_SCRIPT), str(input_file), str(output_pdf)],
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


