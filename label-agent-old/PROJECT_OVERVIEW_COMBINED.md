---
# ⚙️ Cursor Context File — Label Agent / LangGraph Pricing Agent v1.0
**Purpose:**  
This file serves as the **single source of truth** for the *Label Agent* and *LangGraph Pricing Agent* ecosystem.  
Cursor and any connected AI development environments should use this as persistent project context.  
It consolidates the entire architecture, current LangGraph implementation, pricing tools, and operational details.

---

# 🧠 Project Overview — Label Agent / LangGraph Pricing Agent v1.0

_Production-ready system for scanning, vision-based identification, pricing aggregation, and label generation for collectibles using a modular LangGraph agent architecture._

## 🎯 Purpose
Automate **pricing and labeling** for collectibles and retail items (comics, vinyl, cards, toys, etc.).  
Workflow: **Scan → 6-Node LangGraph Agent → Review → Approve → Export**.

---

# 1️⃣ Current System Architecture (LangGraph v1.0)

```
iOS Shortcut → FastAPI (app/main.py)
→ LangGraph PricingAgent (6-node pipeline)
  ├─ Vision Node: Image analysis → structured Pydantic output
  ├─ Market Node: Tool selection → decides which market sources to use
  ├─ Tool Node: Executes selected tools → eBay, Discogs, MyComicShop, etc.
  ├─ Reasoning Node: GPT evaluates trust between sources
  ├─ Valuation Node: Applies deterministic pricing rules
  └─ Explain Node: Generates human-readable reasoning summary
→ Review Page / Approval
→ Google Sheets + Sandpiper
→ Label Printing
```

## Key Components
| Folder | Purpose |
|---------|----------|
| **app/** | FastAPI backend: ingestion, Sheets + Sandpiper integrations |
| **langgraph_tools/** | Modular 6-node agent implementation |
| **langgraph_tools/nodes/** | Individual node implementations (vision, market, tool, reasoning, valuation, explain) |
| **langgraph_tools/config/** | Model configuration (fast/balanced/expert modes) |
| **langgraph_tools/context/** | Persistent shared LLM context for cost efficiency |
| **pricing_tools/** | Market research tools (eBay, Discogs, MyComicShop, ComicBookRealm) |
| **pricing_tools/search_registry.py** | Centralized tool registration |
| **schemas/** | Structured output schemas for different item types |
| **database/** | SQLAlchemy models and operations for session persistence |
| **utils/** | Logging, normalizers, pricing rules, extractors |
| **ebay_utils/** | OAuth token handling for eBay APIs |

---

# 2️⃣ Current Implementation Status (v1.0)

### ✅ Version 1.0 — Fully Functional (COMPLETED)

**Architecture:**
- **6-Node Modular Pipeline**: Vision → Market → Tools → Reasoning → Valuation → Explain
- **Persistent Context System**: Shared LLM context loaded once per session (cost optimization)
- **Autonomous Agent**: Decides which tools to use based on item type
- **Multi-Source Market Data**: eBay, Discogs, MyComicShop with more tools available
- **Deterministic Pricing**: Valuation node applies math-based rules after GPT reasoning
- **Type-Specific Schemas**: Guaranteed JSON structure per item type

**Key Features:**
- **Modular Nodes**: Each node is a separate implementation file
- **Tool Registry**: Centralized search tool management in `search_registry.py`
- **Model Configuration**: Configurable agent modes (fast/balanced/expert)
- **Session Persistence**: Database-backed sessions with learned patterns
- **Real Market Data**: Active integrations with eBay, Discogs, MyComicShop
- **Vision Analysis**: Structured Pydantic output from images
- **Autonomous Reasoning**: Agent evaluates data quality and applies pricing logic

**Active Tools:**
- ✅ **eBay** (`pricing_tools/ebay.py`) - General collectible pricing
- ✅ **Discogs** (`pricing_tools/discogs.py`) - Vinyl record pricing
- ✅ **MyComicShop** (`pricing_tools/search_mycomicshop.py`) - Comic book pricing
- 🔄 **ComicBookRealm** (available but not currently active)
- 🔄 **Heritage Auctions** (available but not currently active)

**Available Tools (Registered but not active):**
- GoCollect (playwright-based, useful but slow)
- Smart Search (aggregator)

---

# 3️⃣ Modular Node Architecture Details

## 3.1 Vision Node (`nodes/vision_node.py`)
**Purpose:** Analyzes image and extracts structured item details.

**Output:**
```python
{
    "title": str,
    "condition": str,
    "category_hint": str,
    "attributes": List[str],
    "raw_summary": str
}
```

**Features:**
- Uses Pydantic model for structured output
- Type-safe data extraction
- Condition detection
- Attribute identification

## 3.2 Market Node (`nodes/market_node.py`)
**Purpose:** Decides which market research tools to call.

**Behavior:**
- Analyzes item details from vision node
- Selects appropriate tools from registry
- Returns tool calls for execution
- Autonomous decision-making (not forced workflow)

## 3.3 Tool Node (`nodes/tool_node.py`)
**Purpose:** Executes selected market research tools.

**Process:**
- Receives tool calls from market node
- Executes tools with proper error handling
- Collects results and maps to IDs
- Returns structured tool output

## 3.4 Reasoning Node (`nodes/reasoning_node.py`)
**Purpose:** GPT-powered evaluation of market data quality.

**Features:**
- Assesses trustworthiness of data sources
- Identifies conflicts between sources
- Flags low-confidence data
- Prepares context for valuation

## 3.5 Valuation Node (`nodes/valuation_node.py`)
**Purpose:** Applies deterministic pricing rules and math.

**Features:**
- Uses pricing rules from `utils/pricing_rules.py`
- Applies condition multipliers
- Calculates final price with rounding
- Deterministic (no AI in this step)

## 3.6 Explain Node (`nodes/explain_node.py`)
**Purpose:** Generates human-readable reasoning summary.

**Output:**
- Clear explanation of pricing decision
- Source attribution
- Confidence indicators
- Notes for review interface

---

# 4️⃣ Configuration & Environment

## 4.1 Model Configuration (`config/model_config.py`)

**Three Agent Modes:**

| Mode | Vision | Pricing | Cost | Use Case |
|------|--------|---------|------|----------|
| **fast** | gpt-4o-mini | gpt-4o-mini | 🟢 Low | Bulk processing |
| **balanced** | gpt-4o | gpt-4o | 🟡 Medium | Standard accuracy |
| **expert** | gpt-5 | gpt-5 | 🔴 High | Maximum quality |

**Set via .env:**
```env
AGENT_MODE=fast  # or balanced, expert
```

## 4.2 Required Environment Variables

```env
# OpenAI
OPENAI_API_KEY=sk-...

# eBay
EBAY_CLIENT_ID=...
EBAY_CLIENT_SECRET=...
EBAY_REFRESH_TOKEN=...

# Discogs (optional)
DISCOGS_TOKEN=...

# Sandpiper
SANDPIPER_USERNAME=...
SANDPIPER_PASSWORD=...

# Google Sheets
APPS_SCRIPT_WEBHOOK=https://script.google.com/...

# Network
LOCAL_IP=10.0.0.66
DEBUG_LOGS=false
```

## 4.3 Environment Setup

```bash
# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Start server
.\.venv\Scripts\uvicorn.exe app.main:app --reload --port 8080 --host 0.0.0.0

# Access
# Local: http://localhost:8080/docs
# Mobile: http://10.0.0.66:8080/docs
```

---

# 5️⃣ Tool Integration

## 5.1 Search Tool Registry (`pricing_tools/search_registry.py`)

**Centralized tool management:**
```python
from pricing_tools.search_registry import ALL_SEARCH_TOOLS

# Currently active tools
ALL_SEARCH_TOOLS = [
    search_ebay,           # ✅ Active
    search_mycomicshop,    # ✅ Active  
    search_discogs_tool,   # ✅ Active
    # search_heritage,     # Available but not active
    # search_comicbookrealm, # Available but not active
    # smart_search,        # Available but slow
]
```

**Adding New Tools:**
1. Create tool in `pricing_tools/` directory
2. Import in `search_registry.py`
3. Add to `ALL_SEARCH_TOOLS` list
4. Agent automatically has access

## 5.2 Tool Execution Flow

1. **Market Node** analyzes item details
2. **Market Node** decides which tools to call
3. **Tool Node** executes tools in parallel (if supported)
4. **Reasoning Node** evaluates data quality
5. **Valuation Node** applies pricing rules
6. **Explain Node** generates summary

---

# 6️⃣ Database & Persistence

## 6.1 Database Models (`database/models.py`)

**Key Models:**
- **PricingSession**: User sessions with activity tracking
- **Item**: Individual priced items with full metadata
- **LearnedPattern**: Patterns learned from pricing sessions
- **UserPreference**: User-specific settings and preferences
- **PricingCache**: Cached API results to avoid repeated calls

## 6.2 Session Utilities (`langgraph_tools/session_utils.py`)

**Functions:**
- `create_session()` - New pricing session
- `get_or_create_session()` - Get active session
- `update_session_activity()` - Track activity
- `price_item_from_image()` - Entry point for pricing

---

# 7️⃣ Output Schemas (`schemas/pricing_schemas.py`)

## 7.1 Schema Types

**COMIC_SCHEMA:**
- Title_Issue, Publisher, Base_Price, Condition, Bullets (3x), AI_Notes

**CARD_SCHEMA:**
- Title, Set, Number, Rarity, Price_Source, Base_Price, Condition, AI_Notes

**RECORD_SCHEMA:**
- Title, Artist, Label, Year, Genre, Base_Price, Condition, AI_Notes

**ANYTHING_SCHEMA:**
- Title, Category, Description, Material, Era, Base_Price, Condition, AI_Notes

## 7.2 Benefits
- **Frontend Consistency**: Guaranteed field names
- **Database Compatibility**: Direct mapping to models
- **Type Safety**: Clear expectations per item type
- **Validation**: Pydantic ensures structure

---

# 8️⃣ Utilities & Supporting Code

## 8.1 Normalizers (`utils/normalizers.py`)
- Normalize condition strings
- Standardize field values
- Clean user input

## 8.2 Pricing Rules (`utils/pricing_rules.py`)
- Condition multipliers
- Rounding rules
- Minimum prices

## 8.3 Format Rules (`langgraph_tools/format_rules.py`)
- Output formatting
- Template generation
- Display optimization

## 8.4 Extractors (`utils/extractors.py`)
- Data extraction utilities
- Regex patterns
- Field parsing

---

# 9️⃣ Current Status & What's Working

## ✅ Fully Implemented & Tested:
- ✅ **6-Node Modular Architecture** - Vision → Market → Tools → Reasoning → Valuation → Explain
- ✅ **Persistent Context System** - Shared LLM context for cost efficiency
- ✅ **Active Tool Integration** - eBay, Discogs, MyComicShop working
- ✅ **Autonomous Agent** - Decides which tools to use
- ✅ **Session Persistence** - Database-backed state management
- ✅ **Type-Specific Schemas** - Guaranteed JSON output
- ✅ **Model Configuration** - Fast/balanced/expert modes
- ✅ **Vision Analysis** - Structured Pydantic output
- ✅ **Review Interface** - Schema-compliant display and editing
- ✅ **Google Sheets & Sandpiper** - Export and barcode generation
- ✅ **iOS Shortcut Pipeline** - Mobile scanning workflow
- ✅ **Production Ready** - End-to-end functionality validated

## 📊 Performance Metrics:
- **Agent Response**: < 10 seconds (with tool calls)
- **Vision Analysis**: < 3 seconds
- **Tool Execution**: < 5 seconds (parallel)
- **Total Pipeline**: < 15 seconds end-to-end

## 🎯 Accuracy:
- **Market Data**: Real-time from multiple sources
- **Pricing Logic**: Deterministic rules + AI reasoning
- **Schema Compliance**: 100% (Pydantic validation)
- **User Experience**: Streamlined with review interface

---

# 🔟 Developer Quick Reference

## Start Dev Server
```bash
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\uvicorn.exe app.main:app --reload --port 8080 --host 0.0.0.0
```

## Key Files
- **Main Entry**: `app/main.py` - FastAPI endpoints
- **LangGraph Agent**: `langgraph_tools/pricing_agent.py` - Orchestrator
- **Nodes**: `langgraph_tools/nodes/` - Individual node implementations
- **Tools**: `pricing_tools/search_registry.py` - Tool registry
- **Schemas**: `schemas/pricing_schemas.py` - Output structures
- **Database**: `database/` - Models and operations

## Common Fixes
- uvicorn not found → activate venv
- Mobile not connecting → use --host 0.0.0.0
- "No 'Inventory #' column" → fix Google Sheet header
- API keys missing → verify .env

---

# 🧩 Summary

**Label Agent v1.0** is a **production-ready LangGraph-powered pricing agent** with:

✅ **Modular 6-Node Architecture**: Vision → Market → Tools → Reasoning → Valuation → Explain  
✅ **Persistent Context System**: Cost-optimized shared LLM context  
✅ **Autonomous Tool Selection**: Agent decides which tools to use  
✅ **Active Market Research**: eBay, Discogs, MyComicShop integrated  
✅ **Deterministic Pricing**: Math-based rules after AI reasoning  
✅ **Session Persistence**: Database-backed state management  
✅ **Type-Safe Output**: Pydantic validation for all schemas  
✅ **Production Ready**: Fully functional end-to-end pipeline  

**Status: ✅ Version 1.0 - Fully Functional and Production Ready**