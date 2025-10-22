---
# ⚙️ Cursor Context File — Label Agent / LangGraph Pricing Agent
**Purpose:**  
This file serves as the **single source of truth** for the *Label Agent* and *LangGraph Pricing Agent* ecosystem.  
Cursor and any connected AI development environments should use this as persistent project context.  
It consolidates the entire architecture, current LangGraph implementation, pricing tools, and future expansion plans.

---

# 🧠 Project Overview — Label Agent / LangGraph Pricing Agent

_Integrated system for scanning, vision-based identification, pricing aggregation, and label generation for collectibles using LangGraph agent architecture._

## 🎯 Purpose
Automate **pricing and labeling** for collectibles and retail items (comics, vinyl, cards, toys, etc.).  
Workflow: **Scan → LangGraph Agent (Vision + Pricing + Reasoning) → Review → Approve → Export**.

---

# 1️⃣ Current System Architecture (LangGraph Implementation)

iOS Shortcut → FastAPI (app/main.py)
→ LangGraph PricingAgent (langgraph_tools/pricing_agent.py)
→ Vision Analysis + Market Research + Pricing Reasoning (All-in-One)
→ Review Page / Approval
→ Google Sheets + Sandpiper
→ Label Printing

## Key Components
| Folder | Purpose |
|---------|----------|
| **app/** | FastAPI backend: ingestion, Sheets + Sandpiper integrations |
| **langgraph_tools/** | LangGraph agent implementation and tools |
| **schemas/** | Structured output schemas for different item types |
| **database/** | SQLAlchemy models and operations for session persistence |
| **pricing_tools/** | Market data modules (Discogs, eBay, Brave, Keepa, Scryfall) - **TO BE RE-INTEGRATED** |
| **ebay_utils/** | OAuth token handling for eBay APIs |
| **utils/** | Logging and shared helpers |
| **logs/** | Tool-specific logs and session data |

---

# 2️⃣ Current Progress & Implementation Status

### ✅ Phase 1 — LangGraph Agent Implementation (COMPLETED)
**Goal:** Replace manual vision processing + pricing with unified LangGraph agent that handles everything.

**Current Implementation:**
- **LangGraph PricingAgent** (`langgraph_tools/pricing_agent.py`) - Unified vision + pricing + reasoning
- **Structured Output Schemas** (`schemas/pricing_schemas.py`) - Type-specific field definitions
- **Database Persistence** (`database/`) - Session management, learned patterns, user preferences
- **FastAPI Integration** (`app/main.py`) - Direct LangGraph agent calls, no intermediate processing
- **Tool Framework** (`langgraph_tools/pricing_tools.py`) - Basic tools for vision analysis and database operations

**Key Features:**
- **Single Agent Processing**: Image → LangGraph Agent → Structured JSON output
- **Type-Specific Reasoning**: Different prompts and logic for comics, cards, records, anything
- **Session Persistence**: Database-backed sessions with learned patterns
- **Structured Output**: Guaranteed JSON schema compliance per item type
- **Vision Integration**: Direct image analysis within LangGraph agent

**Architecture Benefits:**
- **No Double Processing**: Single agent handles vision + pricing + reasoning
- **Better Context**: Agent sees image and can reason about what it sees
- **Unified Memory**: Session persistence across multiple items
- **Tool Integration**: Ready for market research tools integration

### 🔄 Phase 2 — Tool Re-Integration (CURRENT PRIORITY)
**Goal:** Re-add market research tools to LangGraph agent for real pricing data.

**Tools to Re-Integrate:**
- **Discogs API** (`pricing_tools/discogs.py`) - Vinyl record pricing
- **eBay API** (`pricing_tools/ebay.py`) - General collectible pricing  
- **Brave Search** (`pricing_tools/brave_search.py`) - Web pricing fallback
- **Keepa API** (`pricing_tools/keepa.py`) - Amazon pricing data
- **Scryfall API** (`pricing_tools/scryfall.py`) - Magic: The Gathering cards
- **Valuation Logic** (`pricing_tools/valuation_logic.py`) - Human-accurate pricing multipliers

**Implementation Plan:**
1. **Convert Tools to LangChain Tools**: Wrap existing pricing functions with `@tool` decorator
2. **Add Tool Selection Logic**: Agent decides which tools to use based on item type
3. **Integrate with Agent Graph**: Add tool nodes to LangGraph workflow
4. **Maintain Structured Output**: Ensure tools return data compatible with schemas

**Current Status:**
- ✅ LangGraph agent framework ready
- ✅ Database persistence working
- ✅ Basic vision analysis tool implemented
- 🔄 **NEXT**: Re-integrate market research tools
- 🔄 **NEXT**: Add tool selection and reasoning logic

---

# 3️⃣ Current LangGraph Implementation Details

## 3.1 LangGraph PricingAgent (`langgraph_tools/pricing_agent.py`)

**Purpose:** Unified agent that handles vision analysis, market research, and pricing reasoning.

**Key Features:**
- **Type-Specific System Prompts**: Different reasoning logic for comics, cards, records, anything
- **Structured JSON Output**: Guaranteed schema compliance per item type
- **Session Persistence**: Database-backed sessions with learned patterns
- **Vision Integration**: Direct image analysis within agent context
- **Tool Framework**: Ready for market research tool integration

**Current Workflow:**
```python
# Single agent call handles everything
result = pricing_agent.price_item_from_image(
    user_id=user_id,
    image_bytes=image_bytes,
    item_type=type,
)
# Returns structured JSON matching schema
```

**System Prompt Examples:**
- **Comics**: Expert comic identification, age-based pricing, condition assessment
- **Cards**: Trading card expertise, rarity detection, condition multipliers
- **Records**: Discogs knowledge, vinyl condition assessment, genre classification
- **Anything**: General collectible expertise, material identification, era detection

## 3.2 Structured Output Schemas (`schemas/pricing_schemas.py`)

**Purpose:** Guarantee consistent JSON output structure per item type.

**Schema Types:**
- **COMIC_SCHEMA**: Title_Issue, Publisher, Base_Price, Condition, Bullets
- **CARD_SCHEMA**: Title, Set, Number, Rarity, Price_Source, Base_Price, Condition
- **RECORD_SCHEMA**: Title, Artist, Label, Year, Genre, Base_Price, Condition
- **ANYTHING_SCHEMA**: Title, Category, Description, Material, Era, Base_Price, Condition

**Benefits:**
- **Frontend Consistency**: Guaranteed field names for review interface
- **Database Compatibility**: Direct mapping to database models
- **Type Safety**: Clear expectations for each item type

## 3.3 Database Persistence (`database/`)

**Purpose:** Session management, learned patterns, and user preferences.

**Key Models:**
- **PricingSession**: User sessions with activity tracking
- **Item**: Individual priced items with full metadata
- **LearnedPattern**: Patterns learned from pricing sessions
- **UserPreference**: User-specific settings and preferences
- **PricingCache**: Cached API results to avoid repeated calls

**Benefits:**
- **Session Continuity**: Multi-item processing with shared context
- **Learning**: Pattern recognition across pricing sessions
- **Performance**: Cached results reduce API calls
- **User Customization**: Personalized pricing preferences
---

# 4️⃣ Implementation & Testing Details

## 4.1 Environment Setup
```bash
cd C:\dev\python\label-agent
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\uvicorn.exe app.main:app --reload --port 8080 --host 0.0.0.0
```

**Access:**
- Local: http://localhost:8080/docs
- Mobile: http://10.0.0.66:8080/docs
- iOS Shortcut → /ingest endpoint

**Enable Debug Logs:**
```bash
$env:DEBUG_LOGS="true"
```

## 4.2 Required Environment Variables
```env
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
```

## 4.3 Current Testing Status
| Component | Status | Notes |
|-----------|--------|-------|
| LangGraph Agent | ✅ Working | Vision + reasoning + structured output |
| Database Persistence | ✅ Working | Sessions, patterns, preferences |
| FastAPI Integration | ✅ Working | Direct agent calls, no intermediate processing |
| Structured Schemas | ✅ Working | Type-specific JSON output |
| Basic Vision Tool | ✅ Working | Image analysis within agent |
| Market Research Tools | 🔄 **NEXT** | Need to re-integrate Discogs, eBay, etc. |
| Tool Selection Logic | 🔄 **NEXT** | Agent needs to choose appropriate tools |
| Review Interface | ✅ Working | Schema-compliant field display |

**Performance Targets:**
- Price lookup < 5 seconds
- 80%+ accuracy vs manual research  
- 90%+ API success rate

---

# 5️⃣ Next Steps: Tool Re-Integration Plan

## 5.1 Immediate Priority: Market Research Tools

**Step 1: Convert Existing Tools to LangChain Tools**
```python
# Example: Convert discogs.py to LangChain tool
@tool
def search_discogs_release(title: str, artist: str = None) -> Dict[str, Any]:
    """Search Discogs for vinyl record pricing data."""
    # Existing discogs.py logic here
    return {"success": True, "data": discogs_result}
```

**Step 2: Add Tool Selection Logic to Agent**
- Agent analyzes item type and decides which tools to use
- Comics → eBay + Brave Search
- Records → Discogs + eBay  
- Cards → eBay + Scryfall (MTG) + Brave Search
- Anything → eBay + Brave Search

**Step 3: Integrate Tools with LangGraph Workflow**
```python
# Add tool nodes to agent graph
workflow.add_node("market_research", tool_node)
workflow.add_edge("agent", "market_research")
workflow.add_edge("market_research", END)
```

**Step 4: Maintain Structured Output**
- Tools return data compatible with schemas
- Agent combines tool results with vision analysis
- Final output matches schema exactly

## 5.2 Tools Ready for Re-Integration

| Tool | File | Purpose | Status |
|------|------|--------|--------|
| Discogs | `pricing_tools/discogs.py` | Vinyl record pricing | Ready |
| eBay | `pricing_tools/ebay.py` | General collectible pricing | Ready |
| Brave Search | `pricing_tools/brave_search.py` | Web pricing fallback | Ready |
| Keepa | `pricing_tools/keepa.py` | Amazon pricing data | Ready |
| Scryfall | `pricing_tools/scryfall.py` | MTG card pricing | Ready |
| Valuation Logic | `pricing_tools/valuation_logic.py` | Human-accurate multipliers | Ready |

## 5.3 Future Enhancements

**Phase 3: Advanced Agent Features**
- **Multi-Image Processing**: Handle multiple photos per item
- **Batch Processing**: Process stacks of items in single session
- **Learning Integration**: Use learned patterns in pricing decisions
- **User Customization**: Apply user preferences to pricing logic

**Phase 4: Production Features**
- **Caching Layer**: Reduce API calls with intelligent caching
- **Error Recovery**: Graceful handling of API failures
- **Performance Optimization**: Parallel tool execution
- **Monitoring**: LangSmith integration for agent performance tracking

---

# 6️⃣ Current Status & What's Working

## ✅ **Fully Implemented & Tested:**
- **LangGraph Agent Framework**: Unified vision + pricing + reasoning
- **Database Persistence**: Session management, learned patterns, user preferences
- **Structured Output Schemas**: Type-specific JSON compliance
- **FastAPI Integration**: Direct agent calls, no intermediate processing
- **Basic Vision Analysis**: Image processing within agent context
- **Review Interface**: Schema-compliant field display and editing
- **Google Sheets & Sandpiper**: Export and barcode generation
- **iOS Shortcut Pipeline**: Mobile scanning workflow

## 🔄 **Next Priority: Tool Re-Integration**
- **Market Research Tools**: Discogs, eBay, Brave Search, Keepa, Scryfall
- **Tool Selection Logic**: Agent decides which tools to use per item type
- **Valuation Logic**: Human-accurate pricing multipliers
- **Caching Layer**: Reduce API calls with intelligent caching

## 🚀 **Key Benefits of Current Implementation:**
- **Single Source of Truth**: LangGraph agent handles everything
- **No Double Processing**: Eliminated redundant vision + pricing steps
- **Better Context**: Agent sees image and can reason about what it sees
- **Unified Memory**: Session persistence across multiple items
- **Structured Output**: Guaranteed schema compliance per item type
- **Tool Ready**: Framework ready for market research tool integration

---

# 7️⃣ Developer Quick Reference

## Start Dev Server
```bash
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\uvicorn.exe app.main:app --reload --port 8080 --host 0.0.0.0
```

## Common Fixes
- uvicorn not found → activate venv
- Mobile not connecting → use --host 0.0.0.0
- "No 'Inventory #' column" → fix Google Sheet header
- API keys missing → verify .env

## Key Files
- **Main Entry**: `app/main.py` - FastAPI endpoints
- **LangGraph Agent**: `langgraph_tools/pricing_agent.py` - Core agent logic
- **Tools**: `langgraph_tools/pricing_tools.py` - Available tools
- **Schemas**: `schemas/pricing_schemas.py` - Output structure definitions
- **Database**: `database/` - Models and operations

---

# 🧩 Summary

**Label Agent** is now a **LangGraph-powered pricing agent** with:

✅ **Unified Agent Processing**: Single agent handles vision + pricing + reasoning  
✅ **Database Persistence**: Session management and learned patterns  
✅ **Structured Output**: Type-specific JSON schemas  
✅ **Tool Framework**: Ready for market research tool integration  
✅ **Production Ready**: FastAPI, iOS shortcuts, Google Sheets, Sandpiper  

**Next Objective**: Re-integrate market research tools (Discogs, eBay, Brave Search, etc.) as LangChain tools for the agent to use in its reasoning process.