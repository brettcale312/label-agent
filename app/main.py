import os
import io
import json
import uuid
import datetime
import base64
import logging

from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, Form, HTTPException, Request
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from PIL import Image

# ---------------------------------------------------------------------
# Load environment variables early
# ---------------------------------------------------------------------
load_dotenv()

# ---------------------------------------------------------------------
# Local Imports
# ---------------------------------------------------------------------
from app.sheets import append_row, get_next_inventory_number
from app.sandpiper import create_item_and_barcode
from langgraph_tools.pricing_agent import PricingAgent
from schemas.pricing_schemas import get_schema
from app.langgraph_agent_runner import price_image
from database.connection import get_db_session
from database.operations import PricingSessionOps
from utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------
# Logging Setup (rotating log per run)
# ---------------------------------------------------------------------
os.makedirs("logs", exist_ok=True)
timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
run_log_path = os.path.join("logs", f"run_{timestamp}.txt")

file_handler = logging.FileHandler(run_log_path, encoding="utf-8")
file_handler.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
file_handler.setFormatter(formatter)

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(file_handler)

logger.info(f"🧾 Log file started: {run_log_path}")

# ---------------------------------------------------------------------
# Initialize Pricing Agent once globally
# ---------------------------------------------------------------------
pricing_agent = PricingAgent(model_name="gpt-4o-mini")
logger.info("[Startup] PricingAgent initialized globally.")

# ---------------------------------------------------------------------
# FastAPI setup
# ---------------------------------------------------------------------
app = FastAPI(title="Label Agent Starter", version="0.5.6-persistent")
templates = Jinja2Templates(directory="templates")

LOG_DIR = "logs"
SANDPIPER_LOG = os.path.join(LOG_DIR, "sandpiper.log")
DEBUG_LOGS = os.getenv("DEBUG_LOGS", "false").lower() == "true"
ALIGNMENT_DEBUG = os.getenv("ALIGNMENT_DEBUG", "false").lower() == "true"


def log_event(level: str, data: dict):
    """Append timestamped Sandpiper actions to a single log file."""
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{ts}] {level.upper()} → {json.dumps(data, ensure_ascii=False)}\n"
    with open(SANDPIPER_LOG, "a", encoding="utf-8") as f:
        f.write(entry)
    print(f"[{ts}] {level.upper()} -> {json.dumps(data, ensure_ascii=False)}")


def log_alignment_issues(type_: str, missing: list, extras: list, renamed: dict):
    """Write daily rotating alignment log entries (only if ALIGNMENT_DEBUG=true)."""
    if not ALIGNMENT_DEBUG or not (missing or extras or renamed):
        return

    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_tag = datetime.datetime.now().strftime("%Y%m%d")
    log_path = os.path.join(LOG_DIR, f"field_alignment_{date_tag}.log")

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"\n[{ts}] Alignment check for type '{type_}':\n")
        if missing:
            f.write(f"  ⚠️ Missing fields: {', '.join(missing)}\n")
        if extras:
            f.write(f"  🧩 Extra fields (not in schema): {', '.join(extras)}\n")
        if renamed:
            f.write(f"  🔄 Renamed mappings: {json.dumps(renamed, indent=2)}\n")


# ---------------------------------------------------------------------
# INGEST — Persistent LangGraph Agent (Per-User Sessions)
# ---------------------------------------------------------------------
@app.post("/ingest")
async def ingest(request: Request, image: UploadFile, type: str = Form(...)):
    """Upload an image and get structured pricing via LangGraph agent."""
    try:
        image_bytes = await image.read()

        # Derive user_id from cookie or default to 'web_user'
        user_id = request.cookies.get("user_id", "web_user")
        session_key = f"{user_id}_session"

        # Reuse global pricing agent (do not reinitialize each time)
        result = pricing_agent.price_item_from_image(
            user_id=user_id,
            image_bytes=image_bytes,
            item_type=type,
        )

        if not result.get("success"):
            raise Exception(result.get("error", "Unknown failure"))

        fields = result["pricing_result"]

        # Get next inventory number
        next_num = await get_next_inventory_number(type)
        fields["Inventory #"] = next_num or str(uuid.uuid4())[:8]

        # Save structured output to temp file for review
        review_id = str(uuid.uuid4())
        review_path = f"logs/temp_{review_id}.json"
        with open(review_path, "w", encoding="utf-8") as f:
            json.dump({"type": type, "fields": fields}, f, indent=2)

        review_url = f"http://{os.getenv('LOCAL_IP', '10.0.0.66')}:8080/review/{review_id}"
        return JSONResponse({"ok": True, "review_url": review_url})

    except Exception as e:
        logger.error(f"Ingest error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to process image: {e}")


# ---------------------------------------------------------------------
# REVIEW PAGE
# ---------------------------------------------------------------------
@app.get("/review/{session_id}", response_class=HTMLResponse)
async def review_page(request: Request, session_id: str):
    path = f"logs/temp_{session_id}.json"
    if not os.path.exists(path):
        return HTMLResponse("<h3>Session not found.</h3>", status_code=404)

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return templates.TemplateResponse(
        "review.html",
        {
            "request": request,
            "session_id": session_id,
            "data": data["fields"],
            "type_": data.get("type"),
        },
    )


# ---------------------------------------------------------------------
# APPROVE ITEM
# ---------------------------------------------------------------------
@app.post("/approve/{session_id}", response_class=HTMLResponse)
async def approve_item(request: Request, session_id: str):
    """
    Approve and finalize a scanned item.
    Aligns all fields to the schema for the detected item type,
    creates the item in Sandpiper, and appends the finalized row to Sheets.
    """
    form = await request.form()
    path = f"logs/temp_{session_id}.json"

    if not os.path.exists(path):
        return HTMLResponse("<h3>Session expired. Please rescan.</h3>", status_code=404)

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    type_ = data.get("type", "anything")
    fields = dict(form)

    # --- Normalize price formatting ---
    val = fields.get("Price", "").strip()
    if val and not val.startswith("$"):
        try:
            fields["Price"] = f"${float(val):.2f}"
        except ValueError:
            fields["Price"] = f"${val}"

    # --- Inventory Number fallback ---
    fields.setdefault("Inventory #", data["fields"].get("Inventory #", "TEMP-0000"))

    # --- Create item in Sandpiper and generate barcode ---
    try:
        price_dollars = float(fields.get("Price", "$0").replace("$", "") or 0)
        description = (
            fields.get("Title_Issue")
            or fields.get("Title & Issue")
            or fields.get("Title")
            or "Untitled Item"
        )
        log_event("request", {"inv_num": fields["Inventory #"], "desc": description, "price": price_dollars})
        barcode = await create_item_and_barcode(fields["Inventory #"], description, price_dollars)
        fields["Barcode"] = barcode or "ERROR"
        log_event("response", {"barcode": barcode})
    except Exception as e:
        fields["Barcode"] = "ERROR"
        log_event("error", {"error": str(e)})

    # --- Align fields using schema for this type ---
    schema = get_schema(type_)

    fields.setdefault("Inventory #", "TEMP-0000")
    fields.setdefault("Barcode", "")

    missing = [k for k in schema.keys() if k not in fields]
    extras = [k for k in fields.keys() if k not in schema]
    renamed = {}

    if "Title_Issue" in schema:
        if "Title" in fields and not fields.get("Title_Issue"):
            fields["Title_Issue"] = fields["Title"]
            renamed["Title"] = "Title_Issue"

    log_alignment_issues(type_, missing, extras, renamed)

    ordered_fields = {key: fields.get(key, "") for key in schema.keys()}

    for extra_key in ("Inventory #", "Barcode"):
        if extra_key not in ordered_fields and extra_key in fields:
            ordered_fields[extra_key] = fields[extra_key]

    await append_row(type_, ordered_fields)

    if DEBUG_LOGS:
        with open(f"logs/success_{session_id}.json", "w", encoding="utf-8") as f:
            json.dump({"fields": fields, "type": type_}, f, indent=2)

    return RedirectResponse(url=f"/success/{session_id}", status_code=303)


# ---------------------------------------------------------------------
# SUCCESS PAGE
# ---------------------------------------------------------------------
@app.get("/success/{session_id}", response_class=HTMLResponse)
async def success_page(request: Request, session_id: str):
    path = f"logs/success_{session_id}.json"
    fields = {}
    type_ = "anything"

    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        fields = data.get("fields", {})
        type_ = data.get("type", "anything")

    shortcut_map = {
        "card": os.getenv("CARD_SHORTCUT", "Scan Card For Label"),
        "comic": os.getenv("COMIC_SHORTCUT", "Scan Comic For Label"),
        "record": os.getenv("RECORD_SHORTCUT", "Scan Record For Label"),
        "anything": os.getenv("ANYTHING_SHORTCUT", "Scan Anything For Label"),
    }

    shortcut_url = f"shortcuts://run-shortcut?name={shortcut_map.get(type_, shortcut_map['anything'])}"

    return templates.TemplateResponse(
        "success.html",
        {
            "request": request,
            "barcode": fields.get("Barcode", ""),
            "data": fields,
            "type": type_,
            "shortcut_url": shortcut_url,
        },
    )
