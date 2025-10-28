"""
explain_node.py
---------------
Generates a concise, human-readable explanation of how the final price
was chosen — summarizing market sources, reasoning, and adjustments.

✅ Uses persistent LLM context (from base_context)
✅ Mirrors the legacy "AI Notes" logic
✅ Returns label-ready explanation text
"""

from typing import Dict, Any
from langchain_core.messages import HumanMessage
from utils.logger import get_logger
from langgraph_tools.context.base_context import get_llm_context

logger = get_logger("explain_node")


# ---------------------------------------------------------------------
# Explain Node
# ---------------------------------------------------------------------
async def explain_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build a short natural-language summary of the pricing decision.

    Expected state:
      {
          "market_data": {...},
          "reasoning": {...},
          "valuation": {...},
          "current_item": {...}
      }

    Returns:
      {
          "explanation": "...",
          "current_item": {...}
      }
    """
    
    llm = get_llm_context()

    market = state.get("market_data") or {}
    reasoning = state.get("reasoning") or {}
    valuation = state.get("valuation") or {}
    current_item = state.get("current_item") or {}

    # Extract key fields
    title = (
        current_item.get("title")
        or current_item.get("Title & Issue")
        or "Unknown Item"
    )
    category = current_item.get("category_hint") or current_item.get("category") or "general"
    condition = current_item.get("condition", "unspecified")
    venue = current_item.get("venue", "N/A")

    final_price = valuation.get("final_price", 0.0)
    base_price = valuation.get("Base_Price", final_price)
    comment = reasoning.get("comment", "")
    ebay_weight = reasoning.get("ebay_weight", 0)
    discogs_weight = reasoning.get("discogs_weight", 0)

    logger.info(f"💬 Generating pricing explanation for {title}")

    # -----------------------------------------------------------------
    # Build prompt
    # -----------------------------------------------------------------
    prompt = f"""
    You are an expert collectibles appraiser.

    Write a short, professional note (under 80 words) suitable for the
    "AI Notes" field on a vendor price tag.

    Include:
      - Which data source(s) (eBay, Discogs, MyComicShop, etc.) most influenced pricing
      - Any condition, artist, or venue adjustments applied
      - Why the final price (${final_price:.2f}) is fair and realistic for resale
      - Maintain a confident, vendor-facing tone.

    ---
    Market Data: {market}
    Reasoning: eBay={ebay_weight}, Discogs={discogs_weight}, Notes="{comment}"
    Valuation: base={base_price}, final={final_price}
    Item Info: {current_item}
    """
    #logger.warning(f"[ExplainNode] current_item contents: {current_item}")
    # -----------------------------------------------------------------
    # LLM call with graceful fallback
    # -----------------------------------------------------------------
    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        text = getattr(response, "content", str(response)).strip().replace("\n", " ")

        # Clean excess punctuation or markdown if present
        text = text.replace("```json", "").replace("```", "").strip()

        logger.info(f"✅ Explanation generated: {text[:120]}...")
        explanation = text

    except Exception as e:
        logger.error(f"❌ Explanation node failed: {e}")
        explanation = f"AI Notes unavailable: {e}"

    # -----------------------------------------------------------------
    # Return full merged state (so downstream or exports have everything)
    # -----------------------------------------------------------------
    return {
        **state,  # ✅ preserve valuation, reasoning, etc.
        "explanation": explanation,
        "current_item": {
            **current_item,
            "AI Notes": explanation,
            "Base_Price": base_price,
            "Final_Price": final_price,
            "Condition": condition,
            "Venue": venue,
            "Category": category,
        },
    }

