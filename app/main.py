import os
import io
import json
import uuid
import datetime

from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, Form, HTTPException, Request
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from PIL import Image

# Load env vars early
load_dotenv()

# Local imports
from .vision import extract_fields_with_vision
from .pricing import apply_pricing_rules
from .sheets import append_row, get_next_inventory_number
from .sandpiper import create_item_and_barcode
from .models import IngestResponse

app = FastAPI(title="Label Agent Starter", version="0.4.3")

templates = Jinja2Templates(directory="templates")

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)
SANDPIPER_LOG = os.path.join(LOG_DIR, "sandpiper.log")

DEBUG_LOGS = os.getenv("DEBUG_LOGS", "false").lower() == "true"


def log_event(level: str, data: dict):
    """Append timestamped Sandpiper actions to a single log file."""
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{ts}] {level.upper()} → {json.dumps(data, ensure_ascii=False)}\n"
    with open(SANDPIPER_LOG, "a", encoding="utf-8") as f:
        f.write(entry)
    print(entry.strip())


# ------------------------------------------------------------
# INGEST
# ------------------------------------------------------------
@app.post("/ingest", response_model=IngestResponse)
async def ingest(image: UploadFile, type: str = Form(...)):
    if type not in ("card", "comic", "record", "anything"):
        raise HTTPException(status_code=400, detail="type must be one of: card, comic, record, anything")

    img_bytes = await image.read()
    try:
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image file")

    fields = await extract_fields_with_vision(img, type)
    fields = await apply_pricing_rules(type, fields)

    # Get Inventory Number early for review
    inv_num = await get_next_inventory_number(type)
    fields["Inventory #"] = inv_num

    # Save temp JSON for review
    session_id = str(uuid.uuid4())
    temp_path = f"logs/temp_{session_id}.json"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump({"type": type, "fields": fields}, f, indent=2)

    review_url = f"http://{os.getenv('LOCAL_IP', '10.0.0.66')}:8080/review/{session_id}"
    return JSONResponse({"ok": True, "review_url": review_url})


# ------------------------------------------------------------
# REVIEW PAGE
# ------------------------------------------------------------
@app.get("/review/{session_id}", response_class=HTMLResponse)
async def review_page(request: Request, session_id: str):
    path = f"logs/temp_{session_id}.json"
    if not os.path.exists(path):
        return HTMLResponse("<h3>Session not found.</h3>", status_code=404)

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    type_ = data.get("type")

    return templates.TemplateResponse(
        "review.html",
        {
            "request": request,
            "session_id": session_id,
            "data": data["fields"],
            "type_": type_,
        },
    )


# ------------------------------------------------------------
# APPROVE ITEM
# ------------------------------------------------------------
@app.post("/approve/{session_id}", response_class=HTMLResponse)
async def approve_item(request: Request, session_id: str):
    form = await request.form()
    path = f"logs/temp_{session_id}.json"
    if not os.path.exists(path):
        return HTMLResponse("<h3>Session expired. Please rescan.</h3>", status_code=404)

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    type_ = data.get("type")
    fields = dict(form)

    # --- Normalize price formatting ---
    val = fields.get("Price", "").strip()
    if val and not val.startswith("$"):
        try:
            num = float(val)
            fields["Price"] = f"${num:.2f}"
        except ValueError:
            fields["Price"] = f"${val}"

    # --- Inventory Number ---
    if not fields.get("Inventory #"):
        fields["Inventory #"] = data["fields"].get("Inventory #", "TEMP-0000")

    # --- Create in Sandpiper ---
    try:
        price_val = fields.get("Price", "$0").replace("$", "")
        price_dollars = float(price_val) if price_val else 0.0
        description = fields.get("Title", fields.get("Title & Issue", "Untitled Item"))

        log_event("request", {"inv_num": fields["Inventory #"], "desc": description, "price": price_dollars})
        barcode = await create_item_and_barcode(fields["Inventory #"], description, price_dollars)
        log_event("response", {"barcode": barcode})
    except Exception as e:
        barcode = "ERROR"
        log_event("error", {"error": str(e)})

    fields["Barcode"] = barcode

    await append_row(type_, fields)

    if DEBUG_LOGS:
        temp_success_path = f"logs/success_{session_id}.json"
        with open(temp_success_path, "w", encoding="utf-8") as f:
            json.dump({"fields": fields, "type": type_}, f, indent=2)

    return RedirectResponse(url=f"/success/{session_id}", status_code=303)


# ------------------------------------------------------------
# SUCCESS PAGE
# ------------------------------------------------------------
@app.get("/success/{session_id}", response_class=HTMLResponse)
async def success_page(request: Request, session_id: str):
    path = f"logs/success_{session_id}.json"
    fields = {}
    type_ = "anything"

    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        fields = data["fields"]
        type_ = data["type"]

    card_shortcut = os.getenv("CARD_SHORTCUT", "Scan Card For Label")
    comic_shortcut = os.getenv("COMIC_SHORTCUT", "Scan Comic For Label")
    record_shortcut = os.getenv("RECORD_SHORTCUT", "Scan Record For Label")
    anything_shortcut = os.getenv("ANYTHING_SHORTCUT", "Scan Anything For Label")

    shortcut_name = {
        "card": card_shortcut,
        "comic": comic_shortcut,
        "record": record_shortcut,
        "anything": anything_shortcut,
    }.get(type_, anything_shortcut)

    shortcut_url = f"shortcuts://run-shortcut?name={shortcut_name}"

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
