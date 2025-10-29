"""
main.py
--------
FastAPI entry point for Label-Agent / Pricing-Agent system.

Handles:
- Image ingestion for pricing
- Review / approve workflow
- Integration with Sandpiper + Google Sheets
- Unified schema alignment (3 bullets, Base Price, Price Source)
"""

import sys
import asyncio

# ---------------------------------------------------------------------
# 🧠 Windows Python 3.13 fix: ensure Playwright can launch subprocesses
# ---------------------------------------------------------------------
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import os
import json
import uuid
import datetime
import logging

from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, Form, HTTPException, Request
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

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
from utils.normalizers import extract_price_sources  # ✅ shared normalization

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
# FastAPI setup
# ---------------------------------------------------------------------
app = FastAPI(title="Label Agent Starter", version="0.6.2-ingest-enhanced")
templates = Jinja2Templates(directory="templates")

LOG_DIR = "logs"
SANDPIPER_LOG = os.path.join(LOG_DIR, "sandpiper.log")
DEBUG_LOGS = os.getenv("DEBUG_LOGS", "false").lower() == "true"
ALIGNMENT_DEBUG = os.getenv("ALIGNMENT_DEBUG", "false").lower() == "true"

# ---------------------------------------------------------------------
# Initialize Pricing Agent once globally
# ---------------------------------------------------------------------
pricing_agent = PricingAgent()
logger.info("[Startup] PricingAgent initialized globally.")

# ---------------------------------------------------------------------
# Preload persistent LLM context once per process
# ---------------------------------------------------------------------
from langgraph_tools.context.base_context import get_llm_context, reset_global_context


@app.on_event("startup")
async def preload_llm_context():
    """Ensure shared persistent LLM context is loaded once per process."""
    _ = get_llm_context()
    logger.info("[Startup] ✅ Global LLM context preloaded and persistent.")


# ---------------------------------------------------------------------
# Helper Logging Functions
# ---------------------------------------------------------------------
def log_event(level: str, data: dict):
    """Append timestamped Sandpiper actions to a single log file."""
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{ts}] {level.upper()} → {json.dumps(data, ensure_ascii=False)}\n"
    with open(SANDPIPER_LOG, "a", encoding="utf-8") as f:
        f.write(entry)
    print(entry.strip())


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
            f.write(f"  🧩 Extra fields: {', '.join(extras)}\n")
        if renamed:
            f.write(f"  🔄 Renamed: {json.dumps(renamed, indent=2)}\n")


# ---------------------------------------------------------------------
# INGEST — Persistent LangGraph Agent (Per-User Sessions)
# ---------------------------------------------------------------------
@app.post("/ingest")
async def ingest(request: Request, image: UploadFile, type: str = Form(...)):
    """Upload an image and get structured pricing via LangGraph agent."""
    try:
        reset_global_context()
        image_bytes = await image.read()
        user_id = request.cookies.get("user_id", "web_user")

        from langgraph_tools.session_utils import price_item_from_image

        result = price_item_from_image(
            pricing_agent.graph,
            user_id=user_id,
            image_bytes=image_bytes,
            item_type=type,
        )

        if not result.get("success"):
            raise Exception(result.get("error", "Unknown failure"))

        fields = result["pricing_result"]

        # Assign next inventory number
        next_num = await get_next_inventory_number(type)
        fields["Inventory #"] = next_num or str(uuid.uuid4())[:8]

        # Ensure unified presence
        fields.setdefault("Base Price", fields.get("Price", ""))

        # ✅ Normalize Price Source here only if missing or raw
        if not fields.get("Price Source") or "toolu" in fields.get("Price Source", "").lower():
            tool_results = result.get("tool_results", {}) or {}
            fields["Price Source"] = extract_price_sources(tool_results)

        # Save structured output to temporary file for review
        review_id = str(uuid.uuid4())
        review_path = f"logs/temp_{review_id}.json"
        with open(review_path, "w", encoding="utf-8") as f:
            json.dump({"type": type, "fields": fields}, f, indent=2)

        review_url = f"http://{os.getenv('LOCAL_IP', '10.0.0.66')}:8080/review/{review_id}"
        return JSONResponse({"ok": True, "review_url": review_url})

    except Exception as e:
        logger.error(f"[Ingest] ❌ {e}")
        raise HTTPException(status_code=500, detail=f"Failed to process image: {e}")


# ---------------------------------------------------------------------
# REVIEW PAGE
# ---------------------------------------------------------------------
@app.get("/review/{session_id}", response_class=HTMLResponse)
async def review_page(request: Request, session_id: str):
    """Display structured result for final user approval before export."""
    path = f"logs/temp_{session_id}.json"
    if not os.path.exists(path):
        return HTMLResponse("<h3>Session not found.</h3>", status_code=404)

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # ✅ Pass only clean schema fields to template
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
    """Approve and finalize a scanned item."""
    form = await request.form()
    path = f"logs/temp_{session_id}.json"

    if not os.path.exists(path):
        return HTMLResponse("<h3>Session expired. Please rescan.</h3>", status_code=404)

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    type_ = data.get("type", "anything")
    fields = dict(form)

    # Normalize price fields
    for field_name in ("Base Price", "Price"):
        val = fields.get(field_name, "").strip()
        if val:
            try:
                val_float = float(val.replace("$", "").strip())
                fields[field_name] = f"${val_float:.2f}"
            except ValueError:
                fields[field_name] = val

    # Ensure all unified fields exist
    schema = get_schema(type_)
    for key in schema.keys():
        fields.setdefault(key, "")

    # Assign inventory fallback
    fields.setdefault("Inventory #", data["fields"].get("Inventory #", "TEMP-0000"))

    # Generate Sandpiper item and barcode
    try:
        price_dollars = float(fields.get("Price", "$0").replace("$", "") or 0)
        description = fields.get("Title") or "Untitled Item"
        log_event("request", {"inv_num": fields["Inventory #"], "desc": description, "price": price_dollars})
        barcode = await create_item_and_barcode(fields["Inventory #"], description, price_dollars)
        fields["Barcode"] = barcode or "ERROR"
        log_event("response", {"barcode": barcode})
    except Exception as e:
        fields["Barcode"] = "ERROR"
        log_event("error", {"error": str(e)})

    # Schema alignment logging
    missing = [k for k in schema.keys() if k not in fields]
    extras = [k for k in fields.keys() if k not in schema]
    renamed = {}
    log_alignment_issues(type_, missing, extras, renamed)

    # Enforce final ordering per schema
    ordered_fields = {key: fields.get(key, "") for key in schema.keys()}

    # Add essential extras if missing
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
    """Final confirmation page after successful barcode + Sheet sync."""
    path = f"logs/success_{session_id}.json"
    fields, type_ = {}, "anything"

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
