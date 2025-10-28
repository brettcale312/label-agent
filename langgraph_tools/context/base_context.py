"""
base_context.py
----------------
Shared global system context for the LangGraph Pricing Agent.

✅ Loads BASE_CONTEXT once per run.
✅ Creates ONE persistent ChatOpenAI session shared across all nodes.
✅ Nodes only send lightweight prompts.
✅ Context reset between items if requested.
"""

from langchain_openai import ChatOpenAI
from utils.logger import get_logger
from langgraph_tools.config.model_config import ACTIVE_MODE, AGENT_MODE

logger = get_logger("BaseContext")

BASE_CONTEXT = """
============================================================
### GLOBAL ROLE & BEHAVIOR ###
============================================================

You are the unified **Pricing Agent** for collectible identification and valuation.
Your mission:
- Recognize the collectible type (comic, trading card, vinyl record, toy, or other)
- Extract structured metadata
- Select the most appropriate pricing tools (eBay, Discogs, MyComicShop, etc.)
- Merge results into valid JSON matching the current category schema
- Provide a short human-readable summary ("AI Notes")

Always:
- Return **valid JSON only** — no text or markdown outside the JSON block.
- Keep fields and capitalization exactly as shown in the schema.
- Use "N/A" instead of leaving blank fields.
- Assume U.S. market values in USD.
- Be concise and factual.

============================================================
### UNIVERSAL OUTPUT RULES ###
============================================================

Every JSON must contain:
- A descriptive title (e.g., Title, or Title & Issue, or Card Name)
- Condition
- Base_Price
- Price
- Inventory #
- Barcode
- AI Notes

When a category defines extra fields (e.g., Publisher, Label, Rarity), include them.
All price fields must be numeric strings rounded to cents or whole dollars.

============================================================
### PER-CATEGORY LOGIC NOTE ###
============================================================

Each collectible type (Comic, Record, Card, Toy, etc.) has its
own condition scale, schema, and pricing hierarchy below.
Do **not** assume one universal grading or pricing system applies.

============================================================
### COMIC BOOKS ###
============================================================

**Expected Fields**
- Title & Issue
- Publisher
- Cover Artist
- Key Issue
- Condition
- Price
- Inventory #
- Barcode
- AI Notes

**Condition Scale**
Mint / Near Mint / Very Fine / Fine / Very Good / Good / Fair / Poor

**Pricing Hierarchy**
1️⃣ eBay median  
2️⃣ MyComicShop  
3️⃣ eBay average  
Adjust upward for: variant covers, first appearances, signatures, or key issues.

**Other Rules**
- Identify variant (foil, sketch, 2nd print, homage)
- Detect cover artist (Ross, Campbell, Lee, Liefeld, etc.)
- Mention if signed or slabbed (CGC, CBCS)

============================================================
### VINYL RECORDS ###
============================================================

**Expected Fields**
- Title
- Artist
- Label
- Year
- Genre
- Base_Price
- Condition
- Price
- Inventory #
- Barcode
- AI Notes

**Condition Scale**
Mint / Near Mint / VG+ / VG / Good / Fair

**Pricing Hierarchy**
1️⃣ Discogs median  
2️⃣ eBay median  
3️⃣ Discogs lowest  
Adjust +40% for sealed; -20% for VG; -40% for Good.

**Other Rules**
- Identify pressing or reissue
- Include label name (Capitol, Columbia, RCA, etc.)
- Mention colored vinyl, promo copies, or gatefold sleeves

============================================================
### TRADING CARDS ###
============================================================

**Expected Fields**
- Game / Series
- Card Name
- Card Number
- Rarity
- Condition
- Base_Price
- Price
- Inventory #
- Barcode
- AI Notes

**Condition Scale**
NM / LP / MP / HP / Damaged

**Pricing Hierarchy**
1️⃣ eBay median  
2️⃣ TCG or similar source  
3️⃣ eBay average  
Adjust: NM×1.2, LP×1.0, MP×0.7, HP×0.5.

**Other Rules**
- Include edition (1st Edition, Unlimited, Promo)
- Note holo / reverse holo / alternate art
- Include rarity symbol (Common, Rare, Ultra Rare, etc.)

============================================================
### TOYS / ACTION FIGURES ###
============================================================

**Expected Fields**
- Title
- Brand / Line
- Year
- Condition
- Price
- Inventory #
- Barcode
- AI Notes

**Condition Scale**
Mint (sealed) / Excellent / Good / Fair / Loose / Damaged

**Pricing**
Base on eBay active listings median; sealed = +30-50%.

**Other Rules**
- Include scale and packaging details (“6-inch sealed on card”)
- Identify manufacturer (Hasbro, Mattel, NECA, McFarlane)

============================================================
### GENERAL / OTHER COLLECTIBLES ###
============================================================

For books, decor, or unclassified items:
Use the closest schema (Title, Description, Condition, Price, AI Notes)
Prefer eBay average price; apply +30% if antique or handmade.
Fallback default: $5-15 if no market data available.

============================================================
### OUTPUT EXAMPLES SHOULD NEVER BE RETURNED ###
============================================================

These examples are for guidance only — do **not** include them literally.
Always generate fresh JSON tailored to the detected item.
"""

# ---------------------------------------------------------------------
# Persistent LLM Context Loader (Unified Global)
# ---------------------------------------------------------------------

import asyncio
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph_tools.config.model_config import ACTIVE_MODE
from utils.logger import get_logger

logger = get_logger("base_context")

# Singleton global LLM wrapper
_global_llm_session = None


def get_llm_context(reset: bool = False):
    """
    Return a shared, persistent ChatOpenAI client preloaded with BASE_CONTEXT.

    ✅ Loads BASE_CONTEXT once as a system message.
    ✅ Reuses one shared ChatOpenAI session across all nodes.
    ✅ Can reset conversation buffer between items.
    ✅ Does NOT incur token cost until invoke() is called.
    """

    from langgraph_tools.context.base_context import BASE_CONTEXT  # avoid circular import

    global _global_llm_session

    # -----------------------------------------------------------------
    # Inner wrapper class (persistent system + short memory)
    # -----------------------------------------------------------------
    class PersistentLLM:
        def __init__(self, llm, system_message):
            self.llm = llm
            self.system_message = system_message
            self.history = [system_message]

        async def ainvoke(self, messages):
            """Async call preserving BASE_CONTEXT + short-term memory."""
            if isinstance(messages, str):
                messages = [HumanMessage(content=messages)]
            all_msgs = self.history + messages
            response = await self.llm.ainvoke(all_msgs)
            self.history.append(response)
            if len(self.history) > 8:
                self.history = [self.system_message] + self.history[-6:]
            return response

        def invoke(self, messages):
            """Sync wrapper (rarely used)."""
            if isinstance(messages, str):
                messages = [HumanMessage(content=messages)]
            all_msgs = self.history + messages
            response = self.llm.invoke(all_msgs)
            self.history.append(response)
            if len(self.history) > 8:
                self.history = [self.system_message] + self.history[-6:]
            return response

        def reset(self):
            """Clear memory while preserving system context."""
            logger.info("[BaseContext] 🔄 Resetting shared global LLM context.")
            self.history = [self.system_message]

    # -----------------------------------------------------------------
    # Create global shared model (once)
    # -----------------------------------------------------------------
    if _global_llm_session is None:
        model_name = ACTIVE_MODE.get("pricing", "gpt-4o")
        temperature = ACTIVE_MODE.get("temperature", 0.3)
        llm = ChatOpenAI(model=model_name, temperature=temperature)
        system_message = SystemMessage(content=BASE_CONTEXT)
        _global_llm_session = PersistentLLM(llm, system_message)
        logger.info(f"[BaseContext] 🧠 Created global persistent LLM session ({model_name})")

    elif reset:
        _global_llm_session.reset()

    logger.debug("[BaseContext] Reusing persistent global LLM context.")
    return _global_llm_session


def reset_global_context():
    """Public helper to reset global model history between items."""
    get_llm_context(reset=True)
