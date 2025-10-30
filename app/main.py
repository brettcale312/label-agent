"""
main.py
--------
FastAPI entry point for Label-Agent / Pricing-Agent system.

✅ Supports multiple image uploads
✅ Allows frontend (localhost:5173) to connect via CORS
✅ Handles pricing, review, approve, and success workflow
"""

import sys
import asyncio
import os
import json
import uuid
import datetime
import logging
import base64
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, Form, HTTPException, Request
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

# ---------------------------------------------------------------------
# 🧠 Windows Python 3.13 fix: ensure Playwright can launch subprocesses
# ---------------------------------------------------------------------
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

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
from utils.normalizers import extract_price_sources

logger = get_logger(__name__)

# ---------------------------------------------------------------------
# Logging Setup
# ---------------------------------------------------------------------
os.makedirs("logs", exist_ok=True)
timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
run_log_path = os.path.join("logs", f"run_{timestamp}.txt")

file_handler = logging.FileHandler(run_log_path, encoding="utf-8")
file_handler.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
file_handler.setFormatter(formatter)
logging.getLogger().addHandler(file_handler)

logger.info(f"🧾 Log file started: {run_log_path}")

# ---------------------------------------------------------------------
# FastAPI setup
# ---------------------------------------------------------------------
app = FastAPI(title="Label Agent Starter", version="0.6.3-multiimage")
templates = Jinja2Templates(directory="templates")

# ✅ Enable CORS so frontend can connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://10.0.0.66:5173",  # your LAN IP
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
# Preload persistent LLM context
# ---------------------------------------------------------------------
from langgraph_tools.context.base_context import get_llm_context, reset_global_context


@app.on_event("startup")
async def preload_llm_context():
    """Ensure shared persistent LLM context is loaded once per process."""
    _ = get_llm_context()
    logger.info("[Startup] ✅ Global LLM context preloaded.")


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
# INGEST — Multi-image Vision Input (fixed)
# ---------------------------------------------------------------------
@app.post("/ingest")
async def ingest(request: Request, images: list[UploadFile], item_type: str = Form(...)):
    """
    Upload multiple images and get structured pricing via LangGraph agent.
    All images are analyzed together for better accuracy.
    """
    try:
        reset_global_context()
        user_id = request.cookies.get("user_id", "web_user")

        # ✅ Read all uploaded image bytes
        image_bytes_list = [await img.read() for img in images]
        if not image_bytes_list:
            raise HTTPException(status_code=400, detail="No images received.")

        import base64
        b64_images = [
            f"data:image/jpeg;base64,{base64.b64encode(b).decode('utf-8')}"
            for b in image_bytes_list
        ]

        # ✅ Build the message structure expected by VisionNode
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Please analyze and price this {item_type}."},
                    *[{"type": "image_url", "image_url": {"url": url}} for url in b64_images],
                ],
            }
        ]

        state = {
            "messages": messages,
            "user_id": user_id,
            "current_item": {"type": item_type},
            "image_bytes": image_bytes_list[0],  # still keep first image reference
            "item_type": item_type,
        }

        from langgraph_tools.session_utils import price_item_from_image

        # ✅ Pass the proper state instead of raw image
        result = price_item_from_image(
            pricing_agent.graph,
            user_id=user_id,
            image_bytes=image_bytes_list[0],
            item_type=item_type,
            extra_state=state,  # new
        )

        if not result.get("success"):
            raise Exception(result.get("error", "Unknown failure"))

        fields = result["pricing_result"]

        # Assign next inventory number
        next_num = await get_next_inventory_number(item_type)
        fields["Inventory #"] = next_num or str(uuid.uuid4())[:8]

        # Ensure unified presence
        fields.setdefault("Base Price", fields.get("Price", ""))

        # Normalize Price Source
        if not fields.get("Price Source") or "toolu" in fields.get("Price Source", "").lower():
            tool_results = result.get("tool_results", {}) or {}
            fields["Price Source"] = extract_price_sources(tool_results)

        # ✅ Store all uploaded images for later reuse
        img_dir = os.path.join("logs", "uploads")
        os.makedirs(img_dir, exist_ok=True)
        img_paths = []
        for i, b in enumerate(image_bytes_list, start=1):
            path = os.path.join(img_dir, f"{fields['Inventory #']}_{i}.jpg")
            with open(path, "wb") as f:
                f.write(b)
            img_paths.append(path)
        fields["Image Files"] = ", ".join(img_paths)

        # ✅ Save structured output for review
        review_id = str(uuid.uuid4())
        review_path = f"logs/temp_{review_id}.json"
        with open(review_path, "w", encoding="utf-8") as f:
            json.dump({"type": item_type, "fields": fields}, f, indent=2)

        review_url = f"http://{os.getenv('LOCAL_IP', '10.0.0.66')}:8080/review/{review_id}"
        return JSONResponse({"ok": True, "review_url": review_url, "saved_images": img_paths})

    except Exception as e:
        logger.error(f"[Ingest] ❌ {e}")
        raise HTTPException(status_code=500, detail=f"Failed to process images: {e}")

    except Exception as e:
        logger.error(f"[Ingest] ❌ {e}")
        raise HTTPException(status_code=500, detail=f"Failed to process images: {e}")


# ---------------------------------------------------------------------
# REVIEW PAGE
# ---------------------------------------------------------------------
@app.get("/review/{session_id}", response_class=HTMLResponse)
async def review_page(request: Request, session_id: str):
    """Display structured result for final user approval."""
    path = f"logs/temp_{session_id}.json"
    if not os.path.exists(path):
        return HTMLResponse("<h3>Session not found.</h3>", status_code=404)

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return templates.TemplateResponse(
        "review.html",
        {"request": request, "session_id": session_id, "data": data["fields"], "type_": data.get("type")},
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

    for field_name in ("Base Price", "Price"):
        val = fields.get(field_name, "").strip()
        if val:
            try:
                val_float = float(val.replace("$", "").strip())
                fields[field_name] = f"${val_float:.2f}"
            except ValueError:
                pass

    schema = get_schema(type_)
    for key in schema.keys():
        fields.setdefault(key, "")
    fields.setdefault("Inventory #", data["fields"].get("Inventory #", "TEMP-0000"))

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
        {"request": request, "barcode": fields.get("Barcode", ""), "data": fields, "type": type_, "shortcut_url": shortcut_url},
    )
