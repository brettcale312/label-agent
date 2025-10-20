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
from langgraph_tools.pricing_agent import PricingAgent
from database.connection import get_db_session
from database.operations import PricingSessionOps

app = FastAPI(title="Label Agent Starter", version="0.4.3")

templates = Jinja2Templates(directory="templates")

# Global LangGraph agent and session management
_langgraph_agent = None
_current_session_id = None

def get_langgraph_agent():
    """Get or create the global LangGraph agent instance."""
    global _langgraph_agent
    if _langgraph_agent is None:
        _langgraph_agent = PricingAgent(model_name="gpt-4o-mini")
    return _langgraph_agent

def get_or_create_session():
    """Get or create a pricing session."""
    global _current_session_id
    if _current_session_id is None:
        agent = get_langgraph_agent()
        _current_session_id = agent.create_session("web_user", "Web Interface Session")
    return _current_session_id

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
    # Use ASCII-safe arrow for console output to avoid encoding issues
    console_entry = f"[{ts}] {level.upper()} -> {json.dumps(data, ensure_ascii=False)}"
    print(console_entry)


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

    # Get LangGraph session for this request
    langgraph_session_id = get_or_create_session()

    # Save temp JSON for review (include LangGraph session info)
    session_id = str(uuid.uuid4())
    temp_path = f"logs/temp_{session_id}.json"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump({
            "type": type, 
            "fields": fields,
            "langgraph_session_id": langgraph_session_id
        }, f, indent=2)

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
    langgraph_session_id = data.get("langgraph_session_id")

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

    # --- Save to LangGraph database ---
    if langgraph_session_id:
        try:
            from database.operations import ItemOps, LearnedPatternOps
            
            # Get original AI price vs final user-adjusted price
            original_fields = data.get("fields", {})
            ai_price_str = original_fields.get("Price", "$0").replace("$", "")
            final_price_str = fields.get("Price", "$0").replace("$", "")
            
            try:
                ai_price = float(ai_price_str) if ai_price_str else 0
                final_price = float(final_price_str) if final_price_str else 0
                
                # Calculate adjustment ratio
                if ai_price > 0:
                    adjustment_ratio = final_price / ai_price
                    adjustment_made = abs(adjustment_ratio - 1.0) > 0.05  # 5% threshold
                else:
                    adjustment_ratio = 1.0
                    adjustment_made = False
                
                # Prepare item data for LangGraph database
                item_data = {
                    'item_type': type_,
                    'title': fields.get('Title', fields.get('Title & Issue', 'Unknown Item')),
                    'condition': fields.get('Condition', 'unknown'),
                    'base_price': float(fields.get('Base_Price', 0)) if fields.get('Base_Price') else None,
                    'final_price': final_price,
                    'pricing_reasoning': fields.get('AI Notes', ''),
                    'ai_notes': fields.get('AI Notes', ''),
                    'barcode': barcode,
                    'publisher': fields.get('Publisher', ''),
                    'artist': fields.get('Artist', '')
                }
                
                db = get_db_session()
                try:
                    item = ItemOps.create_item(db, langgraph_session_id, item_data)
                    log_event("langgraph_save", {"item_id": item.id, "session_id": langgraph_session_id})
                    
                    # If user made significant adjustment, create learning pattern
                    if adjustment_made:
                        title_key = fields.get('Title', fields.get('Title & Issue', 'Unknown Item'))
                        
                        # Create pattern for this specific item
                        pattern_data = {
                            'ai_price': ai_price,
                            'user_price': final_price,
                            'adjustment_ratio': adjustment_ratio,
                            'reason': f"User adjusted AI price from ${ai_price:.2f} to ${final_price:.2f}",
                            'condition': fields.get('Condition', 'unknown')
                        }
                        
                        LearnedPatternOps.create_pattern(
                            db, langgraph_session_id, 
                            'user_adjustment', 
                            f"{title_key}_{fields.get('Condition', 'unknown')}",
                            pattern_data,
                            confidence_score=0.8,
                            sample_size=1
                        )
                        
                        log_event("langgraph_learning", {
                            "item": title_key,
                            "ai_price": ai_price,
                            "user_price": final_price,
                            "adjustment_ratio": adjustment_ratio
                        })
                        
                finally:
                    db.close()
                    
            except ValueError as e:
                log_event("langgraph_price_parse_error", {"error": str(e)})
                
        except Exception as e:
            log_event("langgraph_error", {"error": str(e)})

    # Ensure fields are in the correct column order for the spreadsheet
    from .models import row_order
    ordered_fields = {}
    column_order = row_order(type_)
    
    # Add fields in the correct column order
    for column in column_order:
        if column in fields:
            ordered_fields[column] = fields[column]
    
    # Add any extra fields that might not be in the column definition
    for key, value in fields.items():
        if key not in ordered_fields:
            ordered_fields[key] = value

    await append_row(type_, ordered_fields)

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
