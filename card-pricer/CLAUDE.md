# card-pricer — Claude Code Briefing

## What This Is
A focused trading card pricing app for an antique mall operator. Takes a photo of a card,
uses AI to identify and price it, shows a review/edit form, then writes to Google Sheets
and generates a Sandpiper barcode. Final step (not yet built) prints a 2x2 thermal label.

Lives at: `label-agent/card-pricer/` (in a git worktree during development)

## Why It Exists (Context)
The owner had a working manual workflow: upload photo to ChatGPT → it identifies + prices
the card → manually import to Sandpiper → print label. This app automates that loop.

A previous attempt (`label-agent/`) was over-engineered — LangGraph 6-node pipeline,
LLM-based tool selection, unused SQLAlchemy DB, handled all item types at once. It was
slow, inconsistent, and hard to maintain. This is the clean rewrite, cards only first.

## Architecture (3 Steps, No LangGraph)

```
POST /ingest (images)
  → app/vision.py     — Claude vision: identify card + generate bullets + price estimate
  → app/pricing.py    — PriceCharting API + eBay Browse API (concurrent, both optional)
  → app/valuation.py  — Adaptive weighted price + booth rounding
  → Save session JSON
GET  /review/{id}     — Editable form (user adjusts any field)
POST /approve/{id}    — Sandpiper barcode + Google Sheets row
GET  /success/{id}    — Show barcode, link to iOS Shortcut for next scan
```

## Key Design Decisions

### Claude as Pricing Backbone
Market tools (PriceCharting, eBay) often return no match for specific cards. Claude's
training knowledge is the always-available baseline. Tools supplement when they work.
Valuation weights adapt: if tools find nothing, Claude estimate is used at 100%.

### PriceCharting Match Validation
PriceCharting always returns *something* even on a bad match. We validate the returned
product name against the search query — if no significant words overlap, we discard the
result. Stopwords list in `pricing.py:_PC_STOPWORDS` covers generic TCG terms.

### Booth Rounding (Robyn's Rules)
- < $1 → $1.00
- $1–$5 → round up to nearest quarter
- $5+ → round up to whole dollar

### Valuation Weights (adaptive)
- PC + eBay + Claude: 40% / 20% / 40%
- PC + Claude only:   50% / 50%
- eBay + Claude only: 40% / 60%
- Claude only:        100% (no market data found)

### AI Provider Swap
Set `AI_PROVIDER=anthropic` or `AI_PROVIDER=openai` in `.env`. No code changes needed.
Config lives in `app/config.py`. Same vision prompt works for both.

## File Map
```
main.py              FastAPI app — 4 routes: /ingest /review /approve /success
app/config.py        AI provider settings + env vars
app/models.py        CardVisionResult schema + CARD_COLUMNS for Sheets
app/vision.py        Claude/OpenAI vision call + VISION_PROMPT
app/pricing.py       PriceCharting + eBay concurrent fetch + match validation
app/valuation.py     Adaptive weighting + condition multiplier + booth rounding
app/agent.py         Orchestrates vision → pricing → valuation, builds session dict
app/sandpiper.py     Sandpiper API: login, create item, generate + retrieve barcode
app/sheets.py        Google Sheets via Apps Script webhook
templates/review.html   Editable review form (card fields + price)
templates/success.html  Barcode display + iOS Shortcut next-scan link
label_print/         Placeholder — user will provide existing thermal label scripts
sessions/            Temp JSON session files (gitignored)
```

## Environment Variables (see .env.example)
```
ANTHROPIC_API_KEY     Required if AI_PROVIDER=anthropic
OPENAI_API_KEY        Required if AI_PROVIDER=openai
PRICECHARTING_API_KEY Optional — enables PriceCharting lookups
EBAY_CLIENT_ID/SECRET/REFRESH_TOKEN + ENABLE_EBAY_TOOL=true
SANDPIPER_USERNAME/PASSWORD/ACCOUNT_ID/BOOTH
APPS_SCRIPT_WEBHOOK   Google Sheets Apps Script URL
LOCAL_IP              Your LAN IP for iOS Shortcut access
PORT                  Default 8001 (8000 is used by old label-agent)
IOS_SHORTCUT_NAME     Name of iOS Shortcut for next-scan link on success page
```

## Run
```powershell
cd card-pricer
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```
Browser test at http://localhost:8001 — upload form is on the index page.
iOS Shortcut POSTs images to http://{LOCAL_IP}:8001/ingest.

## Architecture: v2 Batch Workflow

### Workflow
1. Mobile: Start Batch → photograph cards one by one → each photo runs agent, saves to DB as `pending`
2. Desktop: Review editable grid → approve cards → bulk upload to Sandpiper (rate-limited)
3. Desktop: Print queue → select cards in order → generate PDF → labels print matching physical stack order

### Status lifecycle
`pending` → `approved` → `uploaded` → `printed`

### New file map (v2)
```
app/database.py          SQLite layer — batches + cards tables, all CRUD
templates/mobile/
  capture.html           PWA mobile capture page (installable on iPhone home screen)
templates/desktop/
  dashboard.html         Editable review grid (Tabulator library)
  print.html             Label print queue (ordered by batch + sequence_num)
uploads/                 Card images stored here (gitignored)
labels/                  Generated PDF labels (gitignored)
card_pricer.db           SQLite database (gitignored)
```

### API routes (v2)
```
GET  /                       → redirect to /capture (mobile) or /dashboard (desktop)
GET  /capture                → mobile PWA
GET  /dashboard              → desktop review grid
GET  /print                  → label print queue

POST /api/batch/start        → create batch, returns {batch_id, name}
POST /api/batch/{id}/close   → close batch
GET  /api/batches            → list all batches with card counts
GET  /api/batch/{id}         → batch + its cards

POST /api/ingest             → multipart images, runs agent, saves to DB
GET  /api/cards              → list cards (?batch_id=X&status=Y)
PATCH /api/cards/{id}        → update fields (inline edit)
POST /api/cards/approve      → bulk approve {ids:[...]}

POST /api/batch/{id}/upload  → Sandpiper batch upload (1.5s delay, no retry loops)
POST /api/labels/generate    → build PDF {ids:[...]} in given order
```

### Sandpiper rate limiting
- 1.5s pause between each card (SANDPIPER_DELAY constant in main.py)
- Skips cards that already have a barcode (no double-uploads)
- On error: logs it, marks sandpiper_error field, moves on — no retry loops
- Existing 10s duplicate cooldown in sandpiper.py acts as second safety net

### Label printing
- Script: `C:\dev\python\label_tools\2x2_TradingCard_Labels\make_card_2x2_labels.py`
- Input: tab-separated file: title | bullet_1 | bullet_2 | price_source | final_price | inv_num | barcode
- Output: 2x2" PDF, one label per page
- Called via subprocess from /api/labels/generate
- Override path: set LABEL_SCRIPT_PATH in .env

### PWA installation (iPhone)
- Open http://{LOCAL_IP}:8001/capture in Safari
- Tap Share → Add to Home Screen
- Works like a native app, camera access included

## What's Working
- Vision (Claude identifies card, generates bullets, estimates price)
- PriceCharting lookup with match validation (rejects wrong-card matches)
- eBay lookup (often finds no match for specific cards — expected, Claude fills gap)
- Adaptive valuation + booth rounding
- SQLite database with batch/card lifecycle
- Mobile capture PWA
- Desktop review grid with inline editing (Tabulator)
- Batch Sandpiper upload with rate limiting
- Label print queue with sequence-order preservation
- PDF label generation via existing Python script

## What Still Needs Testing / Doing
- [ ] Test Sandpiper end-to-end (needs real credentials in .env)
- [ ] Test Google Sheets end-to-end (needs APPS_SCRIPT_WEBHOOK)
- [ ] Install as PWA on iPhone and test camera capture flow
- [ ] Add LABEL_SCRIPT_PATH to .env pointing to label script
- [ ] Deploy to smarterasp.net when stable
- [ ] Consider: expand to comics/records once cards are solid

## Known Issues / Watch Out For
- PriceCharting sometimes matches wrong card — match validation helps but isn't perfect
- eBay rarely finds exact card matches — expected, Claude fills the gap
- Anthropic API can return 529 (overloaded) — transient, just retry
- Google Sheets webhook needs full http:// URL in .env
- Label script path must be set correctly (LABEL_SCRIPT_PATH in .env or hardcoded default in main.py)
