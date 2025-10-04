# Label Agent Starter

Phone → FastAPI → (vision/pricing) → Google Sheets (via Apps Script webhook).

## Overview
- **FastAPI** receives photos and a `type` = `card` | `comic`.
- `vision.py` extracts fields (stubbed; replace with your model).
- `pricing.py` enforces your rounding rule and optional price lookup (stubbed).
- `sheets.py` posts rows to your **Apps Script Web App** which appends to the sheet.
- `scripts/test_post.py` lets you test locally with any JPG/PNG.

## Quick Start

### 0) Prereqs
- Python 3.10+
- VS Code
- (Optional) iOS Shortcuts/Android HTTP Shortcuts

### 1) Create & activate a venv
```bash
python -m venv .venv
# Windows
.\.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate
```

### 2) Install deps
```bash
pip install -r requirements.txt
```

### 3) Configure environment
Copy `.env.example` → `.env` and set:
- `APPS_SCRIPT_WEBHOOK` = your deployed Apps Script Web App URL
- (Optional) pricing API keys later

### 4) Run locally
```bash
uvicorn app.main:app --reload --port 8080
```
Open http://localhost:8080/docs to try the `/ingest` endpoint (multipart form).

### 5) Test from CLI
```bash
python scripts/test_post.py --file sample.jpg --type comic
```

### 6) Deploy Google Apps Script
- Open the content in `apps_script/Code.gs` at https://script.google.com
- Bind to your target Google Sheet.
- **File → Project Properties → Scopes:** leave defaults.
- **Deploy → New deployment → Web app**
  - Who has access: *Anyone with the link*
  - Copy the URL → put into your `.env` as `APPS_SCRIPT_WEBHOOK`.

### 7) Phone Shortcut
Follow `shortcuts/ios_shortcut_instructions.md` to create a camera shortcut that POSTs to `https://<your-host>/ingest`.

## Columns & Tabs

### Comics (sheet tab: `Comics`)
`Title & Issue | Bullet 1 | Bullet 2 | Bullet 3 | Publisher | Price`

### Trading Cards (sheet tab: `Cards`)
`Title | Bullet 1 | Bullet 2 | Price Source | Final Price`

> Enforced by `models.py` + `sheets.to_row(...)`

## Next steps
- Swap in your real vision extraction in `vision.py`.
- Wire price lookups in `pricing.py`.
- Add inventory IDs/barcodes if you want the backend to assign them.
- Add duplicate guardrails (hash) if desired.

