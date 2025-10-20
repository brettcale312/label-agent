# Label Agent - Quick Start Guide

## For Future Chat Sessions

**Welcome!** This document provides everything needed to quickly understand and continue work on the Label Agent project.

---

## Project Status

**Current Phase**: Phase 1 Complete ✅  
**Next Phase**: Phase 2 (Pricing Integration) - Ready to Start  
**Last Updated**: January 14, 2025

### What's Working
- ✅ All 4 item types scan successfully (card, comic, record, anything)
- ✅ iOS Shortcuts functional - can scan and get review pages
- ✅ Google Sheets integration working - inventory numbers generated
- ✅ Sandpiper integration working - barcodes created
- ✅ Debug logging active - can see Apps Script responses
- ✅ Server accessible from mobile devices

### What Needs Integration
- 🔄 **Pricing Model**: `pricing_tools/pricing_model.py` not yet integrated into vision workflow
- 🔄 **Market Pricing**: Currently using AI estimates instead of real market data

---

## Quick Setup

### 1. Environment Setup
```bash
# Navigate to project
cd C:\dev\python\label-agent

# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Start server (accessible from mobile)
.\.venv\Scripts\uvicorn.exe app.main:app --reload --port 8080 --host 0.0.0.0
```

### 2. Test Server
- **Local**: http://localhost:8080/docs
- **Mobile**: http://10.0.0.66:8080/docs
- **iOS Shortcut**: Should call http://10.0.0.66:8080/ingest

### 3. Enable Debug Logging
```bash
$env:DEBUG_LOGS="true"
```

---

## Key Files & Their Purpose

### Core Application (`app/`)
- **`main.py`** - FastAPI endpoints and workflow orchestration
- **`vision.py`** - OpenAI Vision integration (NEEDS PRICING INTEGRATION)
- **`pricing.py`** - Price formatting and rounding rules
- **`sheets.py`** - Google Sheets integration (with debug logging)
- **`sandpiper.py`** - Inventory management integration
- **`models.py`** - Data models and column definitions
- **`config.py`** - Configuration constants

### Pricing Tools (`pricing_tools/`)
- **`pricing_model.py`** - Multi-source pricing aggregator (TO BE INTEGRATED)
- **`ebay.py`** - eBay Browse API wrapper
- **`discogs.py`** - Discogs API wrapper
- **`brave_search.py`** - Brave Search API wrapper
- **`duckduckgo_search.py`** - DuckDuckGo search (planned)
- **`scryfall.py`** - MTG card pricing (future)
- **`keepa.py`** - Amazon pricing (future)

### Utilities
- **`ebay_utils/auth.py`** - eBay OAuth token management
- **`utils/logger.py`** - Centralized logging system

---

## Current Workflow

1. **Scan**: iOS Shortcut takes photo → `/ingest` endpoint
2. **Identify**: OpenAI Vision extracts item details
3. **Price**: Vision model estimates price (INACCURATE - needs market data)
4. **Review**: User sees review page on phone
5. **Approve**: Data sent to Google Sheets + Sandpiper
6. **Label**: Barcode generated for custom labels

---

## Next Steps: Phase 2 Integration

**Goal**: Integrate `pricing_tools/pricing_model.py` into `app/vision.py` to replace AI estimates with real market data.

**Key Integration Point**: `app/vision.py` lines 215-242 where prices are currently set by vision estimates.

**Expected Result**: Accurate market-based pricing from eBay, Discogs, and Brave Search.

### Integration Code (Ready to Implement)
```python
# In app/vision.py, replace vision price estimation with:
from pricing_tools.pricing_model import get_best_price

# Extract identification
title = ordered.get("Title") or ordered.get("Title & Issue")
artist = ordered.get("Artist") if type_ == "record" else None

# Get market price
price_result = get_best_price(title, artist=artist, category=type_)

# Use market price if available, fallback to vision estimate
if price_result.get("final_price"):
    ordered["Price"] = f"${price_result['final_price']:.2f}"
else:
    ordered["Price"] = enforce_price(ordered.get("Price", ""), minimum_price)
```

---

## Environment Variables

```env
# Required APIs
OPENAI_API_KEY=sk-...
DISCOGS_TOKEN=...
BRAVE_API_KEY=...
EBAY_APP_ID=...
EBAY_CERT_ID=...
EBAY_REFRESH_TOKEN=...

# Integrations
SANDPIPER_USERNAME=...
SANDPIPER_PASSWORD=...
SANDPIPER_ACCOUNT_ID=...
SANDPIPER_BOOTH=...
APPS_SCRIPT_WEBHOOK=https://script.google.com/...

# Configuration
LOCAL_IP=10.0.0.66
DEBUG_LOGS=false
```

---

## Common Issues & Solutions

### Server Not Accessible from Mobile
**Solution**: Use `--host 0.0.0.0` instead of default localhost

### uvicorn Command Not Found
**Solution**: Use `.\.venv\Scripts\uvicorn.exe` or activate virtual environment first

### Apps Script Errors
**Solution**: Check Google Sheet has "Inventory #" column (with space and #)

### Pricing API Failures
**Solution**: Check API keys and enable `DEBUG_LOGS=true` to see responses

---

## Testing Checklist

### Phase 1 Testing ✅
- [x] All 4 item types scan successfully
- [x] Review pages load on mobile
- [x] Google Sheets integration works
- [x] Inventory numbers generated correctly
- [x] Debug logging shows Apps Script responses
- [x] Server accessible from mobile devices

### Phase 2 Testing (Next)
- [ ] Market pricing integration works
- [ ] Discogs pricing for records
- [ ] eBay pricing for general items
- [ ] Brave Search fallback
- [ ] Price accuracy compared to vision estimates
- [ ] Error handling for API failures

---

## Planning Documents

1. **`PROJECT_STATUS.md`** - Complete project overview and current status
2. **`PHASE_2_PRICING_INTEGRATION.md`** - Detailed Phase 2 implementation plan
3. **`PHASE_3_CONFIGURATION_CLEANUP.md`** - Phase 3 configuration and cleanup plan
4. **`PHASE_4_DOCUMENTATION_FINALIZATION.md`** - Phase 4 documentation plan

---

## Commands to Continue

### Start Development
```bash
# Activate environment and start server
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\uvicorn.exe app.main:app --reload --port 8080 --host 0.0.0.0
```

### Execute Next Phase
```
"Execute Phase 2" - Integrate pricing model into vision workflow
```

### Test Current Functionality
```
"Test Phase 1" - Verify all current functionality works
```

---

## Key Insights

1. **Phase 1 Complete**: All basic functionality working, ready for pricing integration
2. **Pricing Model Ready**: `pricing_tools/pricing_model.py` is built and tested, just needs integration
3. **Network Fixed**: Server accessible from mobile devices using `--host 0.0.0.0`
4. **Debug Logging**: Can see Apps Script responses and API calls
5. **Environment Stable**: Virtual environment and dependencies working correctly

---

## Success Metrics

### Phase 1 Achieved ✅
- All 4 item types working
- Mobile accessibility resolved
- Debug logging functional
- Google Sheets integration stable

### Phase 2 Goals
- Accurate market pricing (80%+ accuracy)
- Multiple API sources working
- Graceful fallback to vision estimates
- <5 second response time

---

**Ready to continue!** The project is in excellent shape with Phase 1 complete and Phase 2 ready to implement. All planning documents are available for reference.
