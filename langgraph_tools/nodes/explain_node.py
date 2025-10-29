"""
explain_node.py
---------------
Generates detailed or concise AI Notes explaining how the final price
was determined — with condition context, price range, and market sources.

✅ Smart $low–$high or “around $X” phrasing
✅ Two modes: detailed (multi-paragraph) or concise (tag-length)
✅ Uses medians + weights to describe reasoning naturally
"""

from typing import Dict, Any
from langchain_core.messages import HumanMessage
from utils.logger import get_logger
from langgraph_tools.context.base_context import get_llm_context

logger = get_logger("explain_node")

# ---------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------
DETAILED_EXPLANATION = True  # Toggle to False for short version


# ---------------------------------------------------------------------
# Helper: format price range naturally
# ---------------------------------------------------------------------
def _format_price_range(medians, final_price: float) -> str:
    if not medians:
        return f"${final_price:.0f}"
    low, high = min(medians), max(medians)
    # Ignore extreme zeros
    if low <= 0 or high <= 0:
        return f"${final_price:.0f}"
    spread = abs(high - low)
    avg = (low + high) / 2
    # Tight range → “around $X”
    if spread / avg <= 0.05:
        return f"around ${round(avg):,}"
    # Normal range → "$6–7" or "$15–20"
    low_fmt = f"{low:,.0f}" if low >= 10 else f"{low:.0f}"
    high_fmt = f"{high:,.0f}" if high >= 10 else f"{high:.0f}"
    return f"${low_fmt}–${high_fmt}"


# ---------------------------------------------------------------------
# Explain Node
# ---------------------------------------------------------------------
async def explain_node(state: Dict[str, Any]) -> Dict[str, Any]:
    llm = get_llm_context()

    market = state.get("market_data") or {}
    reasoning = state.get("reasoning") or {}
    valuation = state.get("valuation") or {}
    current_item = state.get("current_item") or {}

    title = (
        current_item.get("title")
        or current_item.get("Title & Issue")
        or "Unknown Item"
    )
    category = (
        current_item.get("category_hint")
        or current_item.get("category")
        or "collectible"
    ).lower()
    condition = current_item.get("condition", "unspecified").lower()
    venue = current_item.get("venue", "N/A").lower()

    final_price = valuation.get("final_price", 0.0)
    base_price = valuation.get("Base_Price", final_price)
    comment = reasoning.get("comment", "")

    medians = [v.get("median", 0) for v in market.values() if v.get("median")]
    range_text = _format_price_range(medians, final_price)

    weighted = {k: v for k, v in reasoning.items() if "_weight" in k and v > 0.05}
    top_sources = ", ".join(
        s.replace("_weight", "").capitalize()
        for s in sorted(weighted, key=weighted.get, reverse=True)
    ) or "market comparisons"

    logger.info(f"💬 Generating {'detailed' if DETAILED_EXPLANATION else 'concise'} AI Notes for {title}")

    # -----------------------------------------------------------------
    # PROMPT BUILDER
    # -----------------------------------------------------------------
    if DETAILED_EXPLANATION:
        prompt = f"""
        You are a professional collectibles appraiser preparing detailed pricing notes.

        Write 2–4 short paragraphs (120–150 words) explaining how the final price
        of ${final_price:.2f} was determined.

        Structure:
          1️⃣ Identification & Condition Check – confirm what the item is and note any condition or packaging factors.
          2️⃣ Market Value Estimate – summarize comparable prices from {top_sources},
              noting an approximate market range of {range_text}.
          3️⃣ Final Valuation – explain how booth/venue and condition adjustments
              produced the final suggested price of ${final_price:.2f}.

        Keep tone confident and conversational, like a dealer explaining reasoning.
        Mention sources (PriceCharting, eBay, Discogs, MyComicShop, Keepa) if applicable.

        ---
        Item: {title}
        Category: {category}
        Condition: {condition}
        Venue: {venue}
        Market Data: {market}
        Reasoning: {reasoning}
        Valuation: base={base_price}, final={final_price}
        Notes: {comment}
        """
    else:
        prompt = f"""
        You are an experienced collectibles appraiser.

        Write one concise, professional paragraph (≤80 words) summarizing how
        the final price of ${final_price:.2f} was determined.

        Include:
          - Main sources ({top_sources})
          - A brief market range ({range_text})
          - Condition and booth/venue factors
          - Why the final price is realistic for resale

        ---
        Item: {title}
        Category: {category}
        Condition: {condition}
        Venue: {venue}
        Market Data: {market}
        Reasoning: {reasoning}
        Valuation: base={base_price}, final={final_price}
        Notes: {comment}
        """

    # -----------------------------------------------------------------
    # LLM CALL
    # -----------------------------------------------------------------
    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        text = getattr(response, "content", str(response)).strip()
        text = text.replace("```", "").replace("\n", " ").strip()
        explanation = text[0].upper() + text[1:] if text else "AI Notes unavailable."
        logger.info(f"✅ Explanation generated: {explanation[:150]}...")
    except Exception as e:
        logger.error(f"❌ Explanation node failed: {e}")
        explanation = f"AI Notes unavailable: {e}"

    # -----------------------------------------------------------------
    # RETURN MERGED STATE
    # -----------------------------------------------------------------
    return {
        **state,
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
