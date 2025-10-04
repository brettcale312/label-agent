import os
from dotenv import load_dotenv

# load environment variables from .env
load_dotenv()

from fastapi import FastAPI, UploadFile, Form, HTTPException
from fastapi.responses import JSONResponse
from PIL import Image
import io

from .vision import extract_fields_with_vision
from .pricing import apply_pricing_rules
from .sheets import append_row
from .models import IngestResponse

app = FastAPI(title="Label Agent Starter", version="0.1.0")

# Debug: check if API key is loaded
# print("DEBUG KEY:", os.getenv("OPENAI_API_KEY")[:10] if os.getenv("OPENAI_API_KEY") else None)

@app.post("/ingest", response_model=IngestResponse)
async def ingest(image: UploadFile, type: str = Form(...)):
    if type not in ("card", "comic"):
        raise HTTPException(status_code=400, detail="type must be 'card' or 'comic'")

    img_bytes = await image.read()
    try:
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image file")

    fields = await extract_fields_with_vision(img, type, image.filename)
    fields = await apply_pricing_rules(type, fields)
    row = await append_row(type, fields)
    return JSONResponse({"ok": True, "added_row": row})
