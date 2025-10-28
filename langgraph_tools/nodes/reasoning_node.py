"""
reasoning_node.py
-----------------
Compares and interprets market data from eBay, MyComicShop, and Discogs
depending on the item category.

✅ Reads from tool_results (not market_data)
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
    Analyze eBay / Discogs / MyComicShop pricing data and assign source weights.

    Expected input:
      state["tool_results"] = {
          "tool_1": {"source": "eBay", "median": 15.0, "average": 16.2, "sample_count": 35},
          "tool_2": {"source": "Discogs", "median": 12.0, "average": 13.0, "sample_count": 10},
          "tool_3": {"source": "MyComicShop", "median": 3.99, "average": 7.99, "sample_count": 3}
      }

    Returns:
      {
        "market_data": {...},   # normalized numeric results
        "reasoning": {...},     # weights + comment
        "current_item": {...}
      }
    """
    
    llm = get_llm_context()
    tool_results = state.get("tool_results", {}) or {}
    current_item = state.get("current_item", {}) or {}
    title = current_item.get("title", "Unknown Item")
    item_type = (current_item.get("type") or "").lower()

    logger.info(f"🧠 Starting reasoning node for {title}")

    # -----------------------------------------------------------------
    # Normalize tool data → standard dict by source name
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

    # -----------------------------------------------------------------
    # Handle missing or incomplete data
    # -----------------------------------------------------------------
    if not market_data:
        logger.warning("⚠️ No valid market data found in tool_results.")
        return dict(
            state,
            market_data={},
            reasoning={
                "ebay_weight": 1.0,
                "discogs_weight": 0.0,
                "mcs_weight": 0.0,
                "comment": "No valid data found. Defaulted to eBay-only weighting.",
            },
            current_item=current_item,
        )

    # -----------------------------------------------------------------
    # Category-specific heuristics
    # -----------------------------------------------------------------
    ebay = market_data.get("ebay", {})
    discogs = market_data.get("discogs", {})
    mcs = market_data.get("mycomicshop", {})

    ebay_med = ebay.get("median", 0)
    discogs_med = discogs.get("median", 0)
    mcs_med = mcs.get("median", 0)
    ebay_count = ebay.get("sample_count", 0)
    discogs_count = discogs.get("sample_count", 0)
    mcs_count = mcs.get("sample_count", 0)

    e_w = d_w = mcs_w = 0.0

    # --- COMICS ---
    if item_type == "comic":
        if mcs_med and ebay_med:
            e_w, mcs_w = 0.6, 0.4
        elif mcs_med:
            e_w, mcs_w = 0.3, 0.7
        else:
            e_w, mcs_w = 1.0, 0.0
        d_w = 0.0

    # --- RECORDS / VINYL ---
    elif item_type in ("record", "vinyl"):
        if discogs_med and ebay_med:
            e_w, d_w = 0.6, 0.4
        elif discogs_med:
            e_w, d_w = 0.3, 0.7
        else:
            e_w, d_w = 1.0, 0.0
        mcs_w = 0.0

    # --- ALL OTHERS ---
    else:
        e_w = 1.0
        d_w = mcs_w = 0.0

    # -----------------------------------------------------------------
    # Optional refinement via LLM (keeps weights same type)
    # -----------------------------------------------------------------
    reasoning_prompt = f"""
    You are a collectibles pricing expert.
    Review these numeric medians and sample counts and decide if the default
    source weighting below seems reasonable.

    Market data:
    {json.dumps(market_data, indent=2)}

    Item type: {item_type}

    Current weights:
      eBay = {e_w}
      Discogs = {d_w}
      MyComicShop = {mcs_w}

    Respond in valid JSON ONLY:
    {{
      "ebay_weight": float,
      "discogs_weight": float,
      "mcs_weight": float,
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

        e_w = float(reasoning_json.get("ebay_weight", e_w))
        d_w = float(reasoning_json.get("discogs_weight", d_w))
        mcs_w = float(reasoning_json.get("mcs_weight", mcs_w))
        comment = reasoning_json.get("comment", "Weights derived via heuristic + LLM refinement.")
    except Exception as e:
        logger.warning(f"[ReasoningNode] ⚠️ LLM refinement skipped: {e}")
        comment = "Weights derived heuristically (LLM fallback)."

    # -----------------------------------------------------------------
    # Normalize to total 1.0
    # -----------------------------------------------------------------
    total = e_w + d_w + mcs_w
    if total == 0:
        e_w, d_w, mcs_w = 1.0, 0.0, 0.0
    else:
        e_w, d_w, mcs_w = e_w / total, d_w / total, mcs_w / total

    reasoning = {
        "ebay_weight": round(e_w, 2),
        "discogs_weight": round(d_w, 2),
        "mcs_weight": round(mcs_w, 2),
        "comment": comment,
    }

    logger.info(
        f"✅ Reasoning complete: eBay={e_w:.2f}, Discogs={d_w:.2f}, MyComicShop={mcs_w:.2f}"
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
    """Safely convert any numeric-like value to float."""
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except Exception:
        return 0.0
