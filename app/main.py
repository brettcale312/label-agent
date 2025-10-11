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

from .vision import extract_fields_with_vision
from .pricing import apply_pricing_rules
from .sheets import append_row, get_next_inventory_number
from .sandpiper import create_item_and_barcode
from .models import IngestResponse

# === Load Environment ===
load_dotenv()

# === App Setup ===
templates = Jinja2Templates(directory="templates")
app = FastAPI(title="Label Agent Starter", version="0.5.3")

# === Logging / Directory Setup ===
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# === Environment Settings ===
DEBUG_LOGS = os.getenv("DEBUG_LOGS", "false").lower() == "true"
LOCAL_IP = os.getenv("LOCAL_IP", "10.0.0.66")

# === Console Banner ===
mode = "DEBUG" if DEBUG_LOGS else "PRODUCTION"
print(f"\n🚀 Label Agent starting in {mode} mode — logs at /{LOG_DIR}/\n")

# === Rotate Old Logs (older than 7 days) ===
def _cleanup_old_logs():
    cutoff = datetime.datetime.now() - datetime.timedelta(days=7)
    for fname in os.listdir(LOG_DIR):
        fpath = os.path.join(LOG_DIR, fname)
        if not os.path.isfile(fpath):
            continue
        try:
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(fpath))
            if mtime < cutoff:
                os.remove(fpath)
        except Exception:
            pass

_cleanup_old_logs()

# === Daily Log Writer ===
def log_event(level: str, data: dict):
    """Append timestamped Sandpiper actions to daily log file."""
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    day = datetime.datetime.now().strftime("%Y-%m-%d")
    log_path = os.path.join(LOG_DIR, f"sandpiper_{day}.log")

    entry = f"[{ts}] {level.upper()} → {json.dumps(data, ensure_ascii=False)}\n"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(entry)
    if DEBUG_LOGS:
        print(entry.strip())  # show in console only when debugging


# === Health Endpoint ===
@app.get("/health", response_class=JSONResponse)
async def health_check():
    return {
        "status": "ok",
        "mode": "debug" if DEBUG_LOGS else "production",
        "timestamp": datetime.datetime.now().isoformat(),
    }


# === /ingest ===
@app.post("/ingest", response_model=IngestResponse)
async def ingest(image: UploadFile, type: str = Form(...)):
    if type not in ("card", "comic"):
        raise HTTPException(status_code=400, detail="type must be 'card' or 'comic'")

    img_bytes = await image.read()
    try:
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image file")

    fields = await extract_fields_with_vision(img, type)
    fields = await apply_pricing_rules(type, fields)
    session_id = str(uuid.uuid4())

    # ✅ Always save temp file so review page works (even in production)
    temp_path = f"{LOG_DIR}/temp_{session_id}.json"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump({"type": type, "fields": fields}, f, indent=2)

    review_url = f"http://{LOCAL_IP}:8080/review/{session_id}"
    return JSONResponse({"ok": True, "review_url": review_url})


# === /review ===
@app.get("/review/{session_id}", response_class=HTMLResponse)
async def review_page(request: Request, session_id: str):
    path = f"{LOG_DIR}/temp_{session_id}.json"
    if not os.path.exists(path):
        return HTMLResponse("<h3>Session not found.</h3>", status_code=404)

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    type_ = data.get("type")
    price_key = "Price" if type_ == "comic" else "Final Price"

    return templates.TemplateResponse(
        "review.html",
        {
            "request": request,
            "session_id": session_id,
            "data": data["fields"],
            "price_key": price_key,
            "type_": type_,
        },
    )


# === /approve ===
@app.post("/approve/{session_id}", response_class=HTMLResponse)
async def approve_item(request: Request, session_id: str):
    form = await request.form()
    path = f"{LOG_DIR}/temp_{session_id}.json"

    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        type_ = data.get("type")
    else:
        type_ = "card"

    fields = dict(form)

    # Normalize price formatting
    price_key = "Price" if type_ == "comic" else "Final Price"
    val = fields.get(price_key, "").strip()
    if val and not val.startswith("$"):
        try:
            num = float(val)
            fields[price_key] = f"${num:.2f}"
        except ValueError:
            fields[price_key] = f"${val}"

    # Generate inventory number
    inv_num = await get_next_inventory_number(type_)
    fields["Inventory #"] = inv_num

    # Create Sandpiper item and barcode
    try:
        price_val = fields.get(price_key, "$0").replace("$", "")
        price_dollars = float(price_val) if price_val else 0.0
        description = fields.get("Title", fields.get("Title & Issue", "Untitled Item"))

        log_event("request", {"inv_num": inv_num, "desc": description, "price": price_dollars})
        barcode = await create_item_and_barcode(inv_num, description, price_dollars)
        log_event("response", {"barcode": barcode})

    except Exception as e:
        barcode = "ERROR"
        log_event("error", {"error": str(e)})

    fields["Barcode"] = barcode
    await append_row(type_, fields)

    # ✅ Only save success JSON when in debug mode
    if DEBUG_LOGS:
        success_path = f"{LOG_DIR}/success_{session_id}.json"
        with open(success_path, "w", encoding="utf-8") as f:
            json.dump({"fields": fields, "type": type_}, f, indent=2)

    return RedirectResponse(url=f"/success/{session_id}", status_code=303)


# === /success ===
@app.get("/success/{session_id}", response_class=HTMLResponse)
async def success_page(request: Request, session_id: str):
    if DEBUG_LOGS:
        path = f"{LOG_DIR}/success_{session_id}.json"
        if not os.path.exists(path):
            return HTMLResponse("<h3>Success data not found.</h3>", status_code=404)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        fields = data["fields"]
        type_ = data["type"]
    else:
        fields = {}
        type_ = "card"

    price_key = "Price" if type_ == "comic" else "Final Price"
    card_shortcut = os.getenv("CARD_SHORTCUT", "Scan Card For Label")
    comic_shortcut = os.getenv("COMIC_SHORTCUT", "Scan Comic For Label")
    shortcut_name = card_shortcut if type_ == "card" else comic_shortcut
    shortcut_url = f"shortcuts://run-shortcut?name={shortcut_name}"

    return templates.TemplateResponse(
        "success.html",
        {
            "request": request,
            "barcode": fields.get("Barcode", ""),
            "data": fields,
            "price_key": price_key,
            "type": type_,
            "shortcut_url": shortcut_url,
        },
    )
