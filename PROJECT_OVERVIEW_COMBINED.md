---
# ⚙️ Cursor Context File — Label Agent / Pricing Tools
**Purpose:**  
This file serves as the **single source of truth** for the *Label Agent* and *Pricing Tools* ecosystem.  
Cursor and any connected AI development environments should use this as persistent project context.  
It consolidates the entire architecture, phase plans, pricing logic, condition detection, documentation roadmap,  
and the long-term migration plan to **LangChain/LangGraph**.

---

# 🧠 Project Overview — Label Agent / Pricing AI Integration

_Integrated system for scanning, vision-based identification, pricing aggregation, and label generation for collectibles._

## 🎯 Purpose
Automate **pricing and labeling** for collectibles and retail items (comics, vinyl, cards, toys, etc.).  
Workflow: **Scan → Identify → Fetch Market Prices → Apply Human Valuation → Label or Export**.

---

# 1️⃣ System Architecture

iOS Shortcut → FastAPI (app/main.py)
→ Vision Analysis (app/vision.py)
→ Pricing Model (pricing_tools/pricing_model.py)
→ Human Valuation (valuation_logic)
→ Review Page / Approval
→ Google Sheets + Sandpiper
→ Label Printing

## Key Components
| Folder | Purpose |
|---------|----------|
| **app/** | FastAPI backend: ingestion, vision model, Sheets + Sandpiper integrations |
| **pricing_tools/** | Market data modules (Discogs, eBay, Brave, future Keepa & Scryfall) |
| **ebay_utils/** | OAuth token handling for eBay APIs |
| **utils/** | Logging and shared helpers |
| **logs/** | Tool-specific logs |
| **prompts/** | Prompt templates for GPT/Vision |
| **core/** *(planned)* | Central pipeline orchestration, SessionState for LangGraph migration |

---

# 2️⃣ Current Progress & Phases

### ✅ Phase 1 — Cleanup & Stabilization
- Unified logging (`utils.logger`)
- Cleaned `requirements.txt`, removed debug clutter
- Confirmed 4 item types functional (card, comic, record, anything)
- iOS Shortcuts → FastAPI pipeline confirmed
- Google Sheets & Sandpiper integrations stable
- Server accessible from mobile (`--host 0.0.0.0`)

### ✅ Phase 2 — Pricing Integration (COMPLETED)
Goal: Replace Vision-estimated prices with **real market data** via the Pricing Model.

**Integration Point:**  
`app/vision.py` lines 247-315 (market pricing integration section)

**Implementation Summary:**
```python
from pricing_tools.pricing_model import get_best_price
title = ordered.get("Title") or ordered.get("Title & Issue")
artist = ordered.get("Artist") if type_ == "record" else None

price_result = get_best_price(title, artist=artist, category=type_, 
                            condition=condition, venue="antique_store")
if price_result.get("final_price"):
    ordered["Price"] = f"${price_result['final_price']:.2f}"
    # Store base price for comics and cards
    if (type_ == "comic" or type_ == "card") and price_result.get("base_price"):
        ordered["Base_Price"] = price_result["base_price"]
else:
    ordered["Price"] = enforce_price(ordered.get("Price", ""), minimum)
```

**Pricing Logic:**
- **Records**: Human-accurate valuation logic with Discogs + eBay data
- **Comics**: Specialized age-based multipliers with dynamic scaling
- **Cards**: Condition-based multipliers with rarity adjustments  
- **Anything**: eBay + Brave weighted average (75% / 25%)

**Key Features Added:**
- Base_Price field for comics and cards (frontend consistency)
- Condition detection integration
- Antique store venue multipliers
- Retail rounding logic
- Comprehensive fallback system

⚙️ Phase 3 — Configuration Cleanup
Centralize constants (app/config.py)

Create /core/session_state.py (future compatibility with LangGraph)

Optimize async concurrency for pricing model

Prepare config for Keepa/Scryfall integration

🧾 Phase 4 — Documentation Finalization
Inline docstrings for key modules (pricing_model, vision.py)

Architecture diagrams (ARCHITECTURE.md)

API documentation (API_DOCUMENTATION.md)

Deployment guide (DEPLOYMENT.md)

Troubleshooting guide (TROUBLESHOOTING.md)

Production readiness checklist

3️⃣ Core Logic Modules
3.1 Pricing Model (pricing_tools/pricing_model.py)
Purpose: Aggregate real-world pricing across multiple APIs with specialized logic per item type.

**Priority Logic:**
- **Records**: Human-accurate valuation logic (Discogs + eBay + condition detection)
- **Comics**: Specialized age-based pricing with dynamic multipliers
- **Cards**: Condition-based multipliers with rarity adjustments
- **Anything**: eBay + Brave weighted average (75% / 25%)

**Specialized Pricing Functions:**
- `calculate_comic_price()`: Age-based multipliers with dynamic scaling
  - Modern (>2005): 1.1x-1.75x (dynamic based on eBay median)
  - Copper/Bronze (1980-2004): 2.0x multiplier
  - Silver/Golden (<1980): 2.5x multiplier
- `calculate_card_price()`: Rarity and condition-based adjustments
- `estimate_value()`: Human-accurate valuation for records with venue multipliers

**Comic Pricing Logic Details:**
```python
# Dynamic multiplier for modern comics to prevent over-inflation
if base_price <= 5:
    base_multiplier = 1.75
elif base_price <= 8:
    # Linearly reduce from 1.75 → 1.1 across $5-$8
    base_multiplier = 1.75 - (base_price - 5) * (0.65 / 3)
else:
    base_multiplier = 1.1  # gentle boost for high medians
```

**Key APIs:**
- Discogs API (records/media only)
- eBay Browse API (all item types)
- Brave Search API (fallback web pricing)
- Future: Keepa (Amazon), Scryfall (MTG)

3.2 Human-Accurate Valuation Logic (pricing_tools/valuation_logic.py)

**Philosophy:**
Raw market medians ≠ retail booth pricing. System applies human-realistic heuristics to produce believable antique-store prices.

**Venue Multipliers (Antique Store):**
- Base price < $5: 2.5× multiplier
- Base price $5-$10: 1.75× multiplier  
- Base price > $10: 1.2× multiplier

**Retail Rounding Logic:**
- < $3: Round up to nearest $0.25
- $3-$5: Round up to nearest $0.50
- > $5: Round up to next dollar

**Condition Multipliers:**
- **Records**: Sealed/Mint (1.6×), VG+ (1.2×), VG (1.0×), Good (0.7×), Fair (0.5×)
- **Comics**: Near Mint (1.1×), Slabbed (1.2×), Very Fine (1.0×), Fine (0.9×), Very Good (0.8×), Good (0.7×), Fair (0.6×)
- **Cards**: Mint/Near Mint (1.6×), Lightly Played (1.2×), Moderately Played (1.0×), Heavily Played (0.7×), Damaged (0.5×)

3.3 Condition Detection Integration

**Flow:**
1. Vision Model → Detects visible wear and condition from image
2. Condition passed to pricing system → Applies appropriate multipliers
3. Venue Adjustment → Adds antique store multipliers based on base price
4. Final Price → Rounded to retail-friendly figure

**Vision Model Condition Detection:**
- **Records**: Default to "good" condition (protective sleeves)
- **Comics**: Detects condition from visible wear
- **Cards**: Assesses physical condition based on visible cues

**Base_Price Field:**
- Comics and cards store eBay median as `Base_Price` for frontend consistency
- Enables accurate "Pricing by Condition" display in review interface
- Prevents reverse-engineering errors in frontend calculations

**Example Calculation:**
```
eBay median = $4.12 (comic, modern era)
Base multiplier = 1.1× (modern comic >$8)
Condition = near mint → +10% = $4.53
Antique store rounding → $5.00
```
4️⃣ Implementation & Testing Details
4.1 Environment Setup
bash
Copy code
cd C:\dev\python\label-agent
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\uvicorn.exe app.main:app --reload --port 8080 --host 0.0.0.0
Access:

Local: http://localhost:8080/docs

Mobile: http://10.0.0.66:8080/docs

iOS Shortcut → /ingest endpoint

Enable Debug Logs:

$env:DEBUG_LOGS="true"
4.2 Required Environment Variables
env
Copy code
OPENAI_API_KEY=sk-...
DISCOGS_TOKEN=...
BRAVE_API_KEY=...
EBAY_APP_ID=...
EBAY_CERT_ID=...
EBAY_REFRESH_TOKEN=...
SANDPIPER_USERNAME=...
SANDPIPER_PASSWORD=...
APPS_SCRIPT_WEBHOOK=https://script.google.com/...
LOCAL_IP=10.0.0.66
DEBUG_LOGS=false
4.3 Testing Checklist
Phase	Key Tests	Status
1	Vision, Sheets, Sandpiper	✅ Passed
2	Discogs/eBay/Brave pricing integration	✅ Passed
2	Human-accurate valuation logic	✅ Passed
2	Comic age-based pricing	✅ Passed
2	Card condition-based pricing	✅ Passed
2	Base_Price field integration	✅ Passed
2	Frontend pricing by condition display	✅ Passed
3	Config cleanup, session persistence	🔜 Planned
4	Docs & architecture review	🔜 Planned

Performance Targets:

Price lookup < 5 seconds

80%+ accuracy vs manual research

90%+ API success rate

5️⃣ Future Expansion & Migration Plan (LangChain / LangGraph)
5.1 Why Migrate
LangGraph adds structured memory + tool orchestration, removing the need to resend full prompts or manual glue code.
Perfect for continuous “stack processing” (comics, cards, records) while maintaining shared context.

5.2 Hybrid Migration Strategy
Step 1 — Modularize Tools
Keep discogs.py, ebay.py, valuation_logic.py, label_formatter.py stateless.
Each should have clean function signatures like:

def get_price(query: str) -> dict
Step 2 — Create SessionState
Simulate LangGraph state now:

class SessionState:
    def __init__(self):
        self.item_count = 0
        self.results = []
        self.rules = {"rounding": "nearest_dollar"}
Step 3 — Routing Function
Centralize routing by type:

def route_item(item):
    if "comic" in item.category: return "comic"
    elif "record" in item.category: return "record"
    elif "card" in item.category: return "trading_card"
    return "other"
Step 4 — Unified Processing Loop
def process_item(state, item):
    item_type = route_item(item)
    price = run_pricing_tools(item_type, item)
    valuation = apply_valuation(price)
    label = format_label(item, valuation)
    state.results.append(label)
    return label
5.3 Future LangGraph Conversion
Once modularized:

from langgraph.graph import StateGraph

graph = StateGraph(SessionState)
graph.add_node("pricing", discogs_tool)
graph.add_node("valuation", valuation_tool)
graph.add_node("label", formatter_tool)
graph.set_entry_point("pricing")
graph.add_edge("pricing", "valuation")
graph.add_edge("valuation", "label")
Each node becomes a self-contained “agent tool,”
reusing your current pricing functions directly — no rewrites.

5.4 Benefits Summary
Feature	Current	LangGraph
Shared Context	Manual SessionState	Built-in memory
Tool Selection	If/Else routing	Router node
Fallback Handling	Try/Except	Graph branches
Structured I/O	Manual JSON dicts	Pydantic nodes
Cost Efficiency	Full prompt per item	Shared context, minimal tokens

5.5 Migration Roadmap
Phase	Focus	Outcome
Now	Keep tools stateless + add SessionState	LangGraph-ready
After Phase 4	Wrap tools as LangChain @tool functions	Agent-compatible
When UI starts	Convert pipeline → LangGraph flow	Persistent session
Later	Add caching, retrieval memory, LangSmith logging	Production-grade agent

6️⃣ Current Status & What's Working

✅ **Fully Implemented & Tested:**
- Human-accurate valuation logic for records (Discogs + eBay integration)
- Specialized comic pricing with age-based multipliers and dynamic scaling
- Card pricing with condition-based multipliers and rarity adjustments
- Base_Price field integration for comics and cards (frontend consistency)
- "Pricing by Condition" display in review interface
- Antique store venue multipliers and retail rounding logic
- Condition detection integration across all item types
- Comprehensive fallback system for API failures
- Google Sheets and Sandpiper integration
- iOS Shortcut → FastAPI pipeline

✅ **Key Features:**
- Records: Human-accurate pricing with condition detection
- Comics: Age-based multipliers (modern: 1.1-1.75x, copper/bronze: 2.0x, silver/golden: 2.5x)
- Cards: Condition multipliers with rarity adjustments
- Frontend: Real-time pricing by condition display
- Backend: Comprehensive market data aggregation

🚀 **Next Steps:**
- Refine card pricing logic (current focus)
- Add Keepa (Amazon) + Scryfall (MTG) integrations
- Web-based multi-photo front-end
- LangGraph continuous session for "scan stacks"
- eBay listing automation using same pricing tools
- Pricing result caching & trend tracking

7️⃣ Developer Quick Reference
Start Dev Server
bash
Copy code
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\uvicorn.exe app.main:app --reload --port 8080 --host 0.0.0.0
Common Fixes
uvicorn not found → activate venv

Mobile not connecting → use --host 0.0.0.0

“No 'Inventory #' column” → fix Google Sheet header

API keys missing → verify .env

🧩 Summary
Label Agent is now a complete foundation for automated collectible pricing and labeling:

Multi-source pricing aggregation

Human-accurate valuation logic

Vision-based condition detection

Fully documented architecture

Ready path toward LangChain/LangGraph orchestration