"""
reasoning_node.py
-----------------
Compares and interprets market data from eBay, MyComicShop, Discogs, PriceCharting,
and Keepa depending on the item category.

✅ Reads from tool_results
✅ Normalizes numeric values
✅ Applies category-specific weighting heuristics
✅ Optionally refines with LLM context
✅ Prepares unified market_data for valuation_node
"""

import json
import re
from typing import Dict, Any
from langchain_core.messages import HumanMessage
from utils.logger import get_logger
from langgraph_tools.context.base_context import get_llm_context

logger = get_logger("reasoning_node")


# ---------------------------------------------------------------------
# Reasoning Node
# ---------------------------------------------------------------------
async def reasoning_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyze multi-source pricing data and assign source weights.

    Supports:
      - eBay
      - Discogs
      - MyComicShop
      - PriceCharting
      - Keepa (standard or smart)
    """

    llm = get_llm_context()
    tool_results = state.get("tool_results", {}) or {}
    current_item = state.get("current_item", {}) or {}
    title = current_item.get("title", "Unknown Item")
    category_hint = (current_item.get("category_hint") or "").lower()

    logger.info(f"🧠 Starting reasoning node for {title} [{category_hint}]")

    # -----------------------------------------------------------------
    # Normalize tool data
    # -----------------------------------------------------------------
    market_data = {}
    for _, result in tool_results.items():
        if not isinstance(result, dict):
            continue
        src = (result.get("source") or "").lower()
        if not src:
            continue

        market_data[src] = {
            "median": _safe_float(result.get("median") or result.get("median_price")),
            "average": _safe_float(result.get("average") or result.get("average_price")),
            "sample_count": int(result.get("samples") or result.get("sample_count") or 0),
        }

    if not market_data:
        logger.warning("⚠️ No valid market data found in tool_results.")
        return dict(
            state,
            market_data={},
            reasoning={
                "pricecharting_weight": 0.0,
                "ebay_weight": 1.0,
                "discogs_weight": 0.0,
                "keepa_weight": 0.0,
                "mcs_weight": 0.0,
                "comment": "No valid data found. Defaulted to eBay-only weighting.",
            },
            current_item=current_item,
        )

    # -----------------------------------------------------------------
    # Extract individual sources
    # -----------------------------------------------------------------
    ebay = market_data.get("ebay", {})
    discogs = market_data.get("discogs", {})
    mcs = market_data.get("mycomicshop", {})
    pc = market_data.get("pricecharting", {})
    keepa = market_data.get("keepa (amazon)", {}) or market_data.get("keepa", {})

    # Extract medians & counts
    ebay_med, ebay_count = ebay.get("median", 0), ebay.get("sample_count", 0)
    discogs_med, discogs_count = discogs.get("median", 0), discogs.get("sample_count", 0)
    mcs_med, mcs_count = mcs.get("median", 0), mcs.get("sample_count", 0)
    pc_med, pc_count = pc.get("median", 0), pc.get("sample_count", 0)
    keepa_med, keepa_count = keepa.get("median", 0), keepa.get("sample_count", 0)

    # -----------------------------------------------------------------
    # Category-specific heuristic weighting
    # -----------------------------------------------------------------
    e_w = d_w = mcs_w = pc_w = k_w = 0.0

    # --- TRADING CARDS / COMICS / VIDEO GAMES / FUNKO ---
    if category_hint in ("card", "comic", "video game", "funko", "collectible"):
        if pc_med:
            pc_w = 0.7
            e_w = 0.2 if ebay_med else 0.0
            mcs_w = 0.1 if mcs_med else 0.0
        elif mcs_med:
            pc_w = 0.0
            mcs_w = 0.6
            e_w = 0.4 if ebay_med else 0.0
        else:
            e_w = 1.0

    # --- RECORDS / VINYL ---
    elif category_hint in ("record", "vinyl"):
        if discogs_med and ebay_med:
            # if Discogs sample count small, bias toward eBay
            if discogs_count < 5 and ebay_count >= 10:
                d_w, e_w = 0.3, 0.7
            else:
                d_w, e_w = 0.5, 0.5
        elif discogs_med:
            d_w = 1.0
        elif ebay_med:
            e_w = 1.0

    # --- TOYS / AMAZON-TYPE COLLECTIBLES ---
    elif category_hint in ("toy", "sealed", "modern collectible"):
        if keepa_med and ebay_med:
            k_w, e_w = 0.6, 0.4
        elif keepa_med:
            k_w = 1.0
        else:
            e_w = 1.0

    # --- DEFAULT / UNKNOWN ---
    else:
        e_w = 1.0

    # -----------------------------------------------------------------
    # Optional LLM refinement
    # -----------------------------------------------------------------
    reasoning_prompt = f"""
    You are an experienced collectibles appraiser.
    The following sources provided median prices and sample counts:

    {json.dumps(market_data, indent=2)}

    Category: {category_hint}

    Current heuristic weights:
      PriceCharting = {pc_w}
      eBay = {e_w}
      Discogs = {d_w}
      MyComicShop = {mcs_w}
      Keepa = {k_w}

    Review the data and adjust slightly if needed.
    Prioritize data reliability over sample count when applicable.
    Respond ONLY in valid JSON:
    {{
      "pricecharting_weight": float,
      "ebay_weight": float,
      "discogs_weight": float,
      "mcs_weight": float,
      "keepa_weight": float,
      "comment": str
    }}
    """

    try:
        response = await llm.ainvoke([HumanMessage(content=reasoning_prompt)])
        raw_text = getattr(response, "content", str(response)).strip()
        json_blocks = [b for b in re.findall(r"\{.*?\}", raw_text, re.DOTALL)]
        if not json_blocks:
            raise ValueError("No JSON block detected in LLM output.")
        reasoning_json = json.loads(max(json_blocks, key=len))

        pc_w = float(reasoning_json.get("pricecharting_weight", pc_w))
        e_w = float(reasoning_json.get("ebay_weight", e_w))
        d_w = float(reasoning_json.get("discogs_weight", d_w))
        mcs_w = float(reasoning_json.get("mcs_weight", mcs_w))
        k_w = float(reasoning_json.get("keepa_weight", k_w))
        comment = reasoning_json.get("comment", "Weights refined via LLM.")
    except Exception as e:
        logger.warning(f"[ReasoningNode] ⚠️ LLM refinement skipped: {e}")
        comment = "Weights derived heuristically (LLM fallback)."

    # Normalize
    total = e_w + d_w + mcs_w + pc_w + k_w
    if total == 0:
        e_w = 1.0
        total = 1.0

    reasoning = {
        "pricecharting_weight": round(pc_w / total, 2),
        "ebay_weight": round(e_w / total, 2),
        "discogs_weight": round(d_w / total, 2),
        "mcs_weight": round(mcs_w / total, 2),
        "keepa_weight": round(k_w / total, 2),
        "comment": comment,
    }

    logger.info(
        f"✅ Reasoning complete | PriceCharting={pc_w:.2f}, eBay={e_w:.2f}, "
        f"Discogs={d_w:.2f}, MyComicShop={mcs_w:.2f}, Keepa={k_w:.2f}"
    )

    return {
        **state,
        "market_data": market_data,
        "reasoning": reasoning,
        "current_item": current_item,
    }


# ---------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------
def _safe_float(value):
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except Exception:
        return 0.0
