# Label Agent - Project Status & Overview

## Current Status: Phase 1 Complete ✅

**Last Updated:** January 14, 2025  
**Current Phase:** Phase 1 (Cleanup) - COMPLETED  
**Next Phase:** Phase 2 (Pricing Integration) - READY TO START

---

## Project Summary

This is a **multi-agent Python application** that automates pricing and labeling for collectibles (comics, cards, records, Funko Pops, etc.). The system uses:

- **FastAPI** backend with image processing
- **OpenAI Vision** for item identification and initial pricing
- **Multiple pricing APIs** (eBay, Discogs, Brave Search) for market data
- **Google Sheets integration** via Apps Script
- **Sandpiper inventory management** for barcode generation
- **iOS Shortcuts** for mobile scanning workflow

---

## Architecture Overview

```
iOS Shortcut → FastAPI Server → Vision Analysis → Pricing APIs → Review Page → Approval → Google Sheets + Sandpiper
```

### Key Components

1. **`app/`** - Main FastAPI application
   - `main.py` - API endpoints and workflow orchestration
   - `vision.py` - OpenAI Vision integration for item identification
   - `pricing.py` - Price formatting and rounding rules
   - `sheets.py` - Google Sheets integration
   - `sandpiper.py` - Inventory management integration

2. **`pricing_tools/`** - External pricing data sources
   - `pricing_model.py` - Multi-source pricing aggregator (NOT YET INTEGRATED)
   - `ebay.py` - eBay Browse API wrapper
   - `discogs.py` - Discogs API wrapper
   - `brave_search.py` - Brave Search API wrapper
   - `duckduckgo_search.py` - DuckDuckGo search (planned)
   - `scryfall.py` - MTG card pricing (future)
   - `keepa.py` - Amazon pricing (future)

3. **`ebay_utils/`** - eBay authentication
   - `auth.py` - OAuth token management

4. **`utils/`** - Shared utilities
   - `logger.py` - Centralized logging system

---

## Current Workflow

1. **Scan**: iOS Shortcut takes photo and sends to `/ingest` endpoint
2. **Identify**: OpenAI Vision extracts item details (title, category, etc.)
3. **Price**: Vision model estimates price (currently inaccurate)
4. **Review**: User sees review page on phone to edit/approve
5. **Approve**: Data sent to Google Sheets and Sandpiper
6. **Label**: Barcode generated for custom label printing

---

## Phase 1 Accomplishments ✅

### Issues Fixed
- ✅ **Logging inconsistencies** - Unified all modules to use `utils.logger`
- ✅ **Requirements.txt cleanup** - Removed duplicates, added version pins
- ✅ **Commented code removal** - Cleaned up debug blocks in `sheets.py`
- ✅ **Dead code removal** - Removed unused `_price_key_for()` function
- ✅ **DuckDuckGo import** - Kept commented for future use with explanatory comment

### Technical Improvements
- ✅ **Debug logging added** - `sheets.py` now shows Apps Script responses
- ✅ **Virtual environment setup** - Documented proper activation process
- ✅ **Network configuration** - Server now accessible from mobile devices

### Current Status
- ✅ **All 4 item types working** (card, comic, record, anything)
- ✅ **iOS Shortcuts functional** - Can scan and get review pages
- ✅ **Google Sheets integration** - Inventory numbers generated correctly
- ✅ **Debug logging active** - Can see Apps Script responses in terminal

---

## Known Issues & Solutions

### Terminal Environment Setup
**Issue**: `uvicorn` command not recognized in regular PowerShell  
**Solution**: Use `.\.venv\Scripts\uvicorn.exe` or activate virtual environment first  
**Command**: `.\.venv\Scripts\Activate.ps1` then `uvicorn app.main:app --reload --port 8080 --host 0.0.0.0`

### Network Access
**Issue**: Phone couldn't reach local server  
**Solution**: Use `--host 0.0.0.0` instead of default localhost  
**Command**: `uvicorn app.main:app --reload --port 8080 --host 0.0.0.0`

---

## Environment Variables Required

```env
# API Keys
OPENAI_API_KEY=sk-...
DISCOGS_TOKEN=...
BRAVE_API_KEY=...
EBAY_APP_ID=...
EBAY_CERT_ID=...
EBAY_REFRESH_TOKEN=...

# Sandpiper Integration
SANDPIPER_USERNAME=...
SANDPIPER_PASSWORD=...
SANDPIPER_ACCOUNT_ID=...
SANDPIPER_BOOTH=...

# Google Sheets Integration
APPS_SCRIPT_WEBHOOK=https://script.google.com/...

# Server Configuration
LOCAL_IP=10.0.0.66

# iOS Shortcuts (optional)
CARD_SHORTCUT=Scan Card For Label
COMIC_SHORTCUT=Scan Comic For Label
RECORD_SHORTCUT=Scan Record For Label
ANYTHING_SHORTCUT=Scan Anything For Label

# Feature Flags
DEBUG_LOGS=false
ENV=dev
```

---

## Next Steps: Phase 2

**Goal**: Integrate `pricing_tools/pricing_model.py` into the vision workflow to replace AI-estimated pricing with real market data.

**Key Integration Point**: `app/vision.py` lines 215-242 where prices are currently set by vision estimates.

**Expected Outcome**: Accurate market-based pricing from eBay, Discogs, and Brave Search instead of unreliable AI estimates.

---

## File Structure

```
label-agent/
├── app/                    # Main FastAPI application
│   ├── main.py            # API endpoints and workflow
│   ├── vision.py          # OpenAI Vision integration
│   ├── pricing.py         # Price formatting rules
│   ├── sheets.py          # Google Sheets integration
│   ├── sandpiper.py       # Inventory management
│   ├── models.py          # Data models and column definitions
│   └── config.py          # Configuration constants
├── pricing_tools/         # External pricing APIs
│   ├── pricing_model.py   # Multi-source aggregator (TO BE INTEGRATED)
│   ├── ebay.py           # eBay Browse API
│   ├── discogs.py        # Discogs API
│   ├── brave_search.py   # Brave Search API
│   ├── duckduckgo_search.py # DuckDuckGo (planned)
│   ├── scryfall.py       # MTG cards (future)
│   └── keepa.py          # Amazon pricing (future)
├── ebay_utils/           # eBay authentication
│   └── auth.py          # OAuth token management
├── utils/               # Shared utilities
│   └── logger.py       # Centralized logging
├── logs/               # Application logs
├── templates/          # HTML templates
├── requirements.txt    # Python dependencies
└── README.md          # Project documentation
```

---

## Testing Checklist

### Phase 1 Testing ✅
- [x] All 4 item types scan successfully
- [x] Review pages load on mobile
- [x] Google Sheets integration works
- [x] Inventory numbers generated correctly
- [x] Debug logging shows Apps Script responses
- [x] Server accessible from mobile devices

### Phase 2 Testing (Pending)
- [ ] Market pricing integration works
- [ ] Discogs pricing for records
- [ ] eBay pricing for general items
- [ ] Brave Search fallback
- [ ] Price accuracy compared to vision estimates
- [ ] Error handling for API failures

---

## Development Commands

### Start Server
```bash
# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Start server (accessible from mobile)
uvicorn app.main:app --reload --port 8080 --host 0.0.0.0
```

### Test Apps Script
```bash
# Test inventory number generation
curl "https://script.google.com/macros/s/YOUR_SCRIPT_ID/exec?type=card"
```

### Debug Logging
```bash
# Enable debug logging
$env:DEBUG_LOGS="true"
```

---

## Future Enhancements

1. **Phase 3**: Configuration cleanup and temp file management
2. **Phase 4**: Documentation updates
3. **Future**: Keepa integration for general retail items
4. **Future**: Scryfall integration for MTG cards
5. **Future**: LangChain/LangGraph for intelligent tool selection
6. **Future**: Confidence scoring for pricing results
7. **Future**: Pricing result caching
8. **Future**: Web frontend instead of iOS Shortcuts
9. **Future**: Multi-photo support (3-5 photos per item)
10. **Future**: eBay listing tool using pricing_tools
