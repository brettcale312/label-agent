"""
market_node.py
---------------
LangGraph Market Node

Determines which market tools (eBay, MyComicShop, Discogs, etc.)
should be called based on recognized item information.

✅ Uses the persistent LLM context from `base_context`
✅ Writes tool_calls into state for downstream ToolNode
✅ Includes barcode, variant, and artist when available
✅ Performs record-specific artist inference when needed
"""

import re
import json
from langchain_core.messages import HumanMessage, AIMessage
from utils.logger import get_logger
from langgraph_tools.context.base_context import get_llm_context
from langgraph_tools.config.model_config import AGENT_MODE

logger = get_logger("market_node")


# ---------------------------------------------------------------------
# Market Node
# ---------------------------------------------------------------------
async def market_node(state):
    """Decide which market tools to use and build structured queries."""

    llm = get_llm_context()
    logger.info(f"[MarketNode] 🧠 Using persistent context | Mode={AGENT_MODE.upper()}")
    
    current_item = state.get("current_item", {}) or {}
    category_hint = current_item.get("category_hint", "general")

    title = current_item.get("title") or ""
    issue = current_item.get("issue_number") or ""
    variant = current_item.get("variant") or ""
    artist = current_item.get("artist") or ""
    condition = current_item.get("condition") or ""
    barcode = current_item.get("barcode") or ""
    attributes = ", ".join(a for a in current_item.get("attributes", []) if a)

    # -----------------------------------------------------------------
    # 🎵 Optional record enhancement: infer missing artist
    # -----------------------------------------------------------------
    if category_hint == "record" and not artist:
        try:
            enrichment_prompt = f"""
            You are a professional music catalog expert.
            The album title is "{title}".
            Guess the most likely artist or band associated with that title.
            Respond ONLY with the artist name, or 'Unknown' if unsure.
            """
            response = await llm.ainvoke([HumanMessage(content=enrichment_prompt)])
            artist_name = getattr(response, "content", "").strip()
            if artist_name and artist_name.lower() != "unknown":
                current_item["artist"] = artist_name
                artist = artist_name
                logger.info(f"[MarketNode] 🎵 Inferred artist for '{title}': {artist_name}")
        except Exception as e:
            logger.warning(f"[MarketNode] ⚠️ Artist inference failed: {e}")

    # -----------------------------------------------------------------
    # 🔍 Build query_context based on item type
    # -----------------------------------------------------------------
    if category_hint == "comic":
        query_context = f"{title} {issue} {variant} {condition}".strip()
    elif category_hint == "record":
        query_context = f"{artist} {title} {condition}".strip()
    elif category_hint == "card":
        query_context = f"{title} {attributes} {condition}".strip()
    else:
        query_context = f"{title} {attributes} {condition}".strip()

    # Add barcode if available (helps eBay accuracy)
    if barcode and barcode not in query_context:
        query_context = f"{query_context} {barcode}".strip()

    logger.info(f"[MarketNode] 🔎 Query context: {query_context}")

    # -----------------------------------------------------------------
    # Build the LLM prompt for tool selection (balanced priorities)
    # -----------------------------------------------------------------
    market_prompt = f"""
    You are the market intelligence model for collectibles.
    Choose the most reliable pricing tools for this item based on its category.

    Item info: "{query_context}"
    Category: {category_hint}

    🔧 Available tools:
      - search_pricecharting_tool → Primary for trading cards (Pokemon, MTG, YuGiOh), comics, video games, and Funko Pops.
      - search_mycomicshop → Secondary for comics, use alongside PriceCharting when available.
      - search_discogs → Use for vinyl records to retrieve structured catalog data.
      - search_ebay → Use for all collectibles as a broad market cross-check or when Discogs/PriceCharting have sparse data.
      - search_keepa_smart_tool → Optional confirmation for Amazon-listed items (toys, games, or collectibles).

    💡 Guidance:
      • Comics, trading cards, Funko Pops, and video games → Always include search_pricecharting_tool.
      • Vinyl records → Use both search_discogs and search_ebay.
          - If Discogs returns many listings, treat it as the stronger signal.
          - If Discogs returns few listings, rely more on eBay.
      • Toys or collectibles without a clear category → Pair search_ebay with search_keepa_smart_tool.
      • When PriceCharting returns only one "loose" value, still treat it as reliable — it's aggregated from many transactions.
      • Prefer specialized tools first, then supplement with eBay for broader coverage.
      • Never exclude a strong specialized source just because eBay data exists.

    Respond ONLY with tool call syntax, one per line, e.g.:
      search_pricecharting_tool("Miraidon EX 253/198 Pokemon card")
      search_ebay("Miraidon EX 253/198 Pokemon card")
      search_discogs("Pink Floyd - The Wall vinyl LP")
      search_ebay("Pink Floyd - The Wall vinyl LP")
      search_mycomicshop("Amazing Spider-Man #300 Near Mint")
      search_pricecharting_tool("Amazing Spider-Man #300 Near Mint")
    """

    try:
        response = await llm.ainvoke([HumanMessage(content=market_prompt)])
        text = getattr(response, "content", "").strip()
    except Exception as e:
        logger.error(f"[MarketNode] ❌ Market prompt failed: {e}")
        text = ""

    # -----------------------------------------------------------------
    # Parse and build tool calls
    # -----------------------------------------------------------------
    matches = re.findall(r"(\w+)\((?:\"|')?([^\"'\)]+)(?:\"|')?\)", text)
    tool_calls = []

    for i, (name, query) in enumerate(matches):
        args = {"query": query}
        if name == "search_ebay" and category_hint:
            args["category_hint"] = category_hint
        tool_calls.append({"name": name, "args": args, "id": f"toolu_{i+1}"})

    # Default fallback if nothing parsed
    if not tool_calls:
        args = {"query": query_context or title or "collectible"}
        if category_hint:
            args["category_hint"] = category_hint
        tool_calls = [{"name": "search_ebay", "args": args, "id": "toolu_1"}]

    # ✅ Return with tool_calls directly in state
    return {
        **state,
        "messages": state.get("messages", []) + [AIMessage(content=f"Tool selection: {text or query_context}")],
        "current_item": current_item,
        "tool_calls": tool_calls,
    }
