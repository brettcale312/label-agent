"""
pricing_node.py
----------------
Final pricing synthesis node for the LangGraph Pricing Agent.

Merges vision + tool data → structured pricing output (JSON).
Applies artist premiums and condition adjustments.
Now supports dynamic model selection via model_config.py ("good / better / best").
"""

import json
import re
from typing import Dict, Any
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_openai import ChatOpenAI
from pricing_tools.valuation_logic import ARTIST_PREMIUMS
from schemas.pricing_schemas import get_schema
from utils.logger import get_logger
from langgraph_tools.config.model_config import ACTIVE_MODE, AGENT_MODE

logger = get_logger("pricing_node")


# ---------------------------------------------------------------------
# Pricing Node
# ---------------------------------------------------------------------
async def pricing_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Merge vision + tool data → structured pricing output (JSON)."""

    # ---------------------------------------------------------------
    # Dynamic model selection
    # ---------------------------------------------------------------
    model_name = ACTIVE_MODE["pricing"]
    temperature = ACTIVE_MODE["temperature"]
    model = ChatOpenAI(model=model_name, temperature=temperature)
    logger.info(f"[PricingNode] 🧠 Mode={AGENT_MODE.upper()} | Model={model_name}")

    # ---------------------------------------------------------------
    # Extract state data
    # ---------------------------------------------------------------
    type_ = state.get("current_item", {}).get("type", "anything").lower()
    structure = get_schema(type_)
    tool_data = state.get("tool_results", {}) or {}
    current_item = state.get("current_item", {}) or {}

    # ---------------------------------------------------------------
    # Summarize tool data
    # ---------------------------------------------------------------
    summaries = []
    for v in tool_data.values():
        if isinstance(v, dict):
            src = v.get("source")
            med = v.get("median") or v.get("median_price")
            avg = v.get("average") or v.get("average_price")
            count = v.get("samples") or v.get("sample_count")
            summaries.append(f"{src}: median={med}, avg={avg}, samples={count}")

    if summaries:
        logger.info("[PricingNode] 🔧 " + " | ".join(summaries))

    # ---------------------------------------------------------------
    # Derive Base_Price
    # ---------------------------------------------------------------
    base_price = None
    for v in tool_data.values():
        if isinstance(v, dict):
            for val in v.values():
                if isinstance(val, (int, float)) and val > 0:
                    base_price = val
                    break
                if isinstance(val, str) and val.replace(".", "", 1).isdigit():
                    base_price = float(val)
                    break
        if base_price:
            break

    # ---------------------------------------------------------------
    # Apply artist premium multiplier
    # ---------------------------------------------------------------
    if base_price:
        attr_text = " ".join(str(a).lower() for a in current_item.get("attributes", []) if a)
        for artist, mult in ARTIST_PREMIUMS.items():
            if artist in attr_text:
                base_price = round(base_price * mult, 2)
                logger.info(f"[PricingNode] 🎨 Artist premium applied: {artist} ×{mult}")
                break

        current_item["Base_Price"] = base_price
        logger.info(f"[PricingNode] 💵 Base_Price: {base_price}")
    else:
        logger.info("[PricingNode] ⚠️ No numeric Base_Price detected.")
        current_item["Base_Price"] = "N/A"

    # ---------------------------------------------------------------
    # Build message history
    # ---------------------------------------------------------------
    tool_messages = [
        {"role": "tool", "tool_call_id": k, "content": json.dumps(v, indent=2)}
        for k, v in tool_data.items()
    ]

    first_human = next((m for m in state["messages"] if isinstance(m, HumanMessage)), None)
    last_tool_msg = next(
        (m for m in reversed(state["messages"]) if isinstance(m, AIMessage) and getattr(m, "tool_calls", None)),
        None,
    )

    messages = [SystemMessage(content="You are a pricing agent synthesizing market data and vision recognition results.")]
    if first_human:
        messages.append(first_human)
    if last_tool_msg:
        messages.append(last_tool_msg)
    messages.extend(tool_messages)

    # ---------------------------------------------------------------
    # Context prompt by item type
    # ---------------------------------------------------------------
    context = {
        "comic": "You are an expert in comic book pricing; include 3 concise bullets.",
        "card": "You are an expert in trading card valuation; include rarity and condition notes.",
        "record": "You are an expert in vinyl record valuation; include label, pressing, and year.",
    }.get(type_, "You are an expert appraiser of collectibles.")

    pricing_prompt = f"""
You have recognition data and summarized tool results.

Recognition data:
{json.dumps(current_item, indent=2)}

Output ONLY valid JSON using this schema:
{json.dumps(structure, indent=2)}

Rules:
- Fill every field.
- Base_Price = median/lowest from tools (after adjustments).
- Adjust final 'Price' based on condition (e.g., NM ×1.2, G ×0.6).
- Include reasoning in 'AI Notes'.
{context}
"""

    messages.append(SystemMessage(content=pricing_prompt))

    # ---------------------------------------------------------------
    # Generate structured final JSON
    # ---------------------------------------------------------------
    try:
        response = await model.ainvoke(messages)
        content = getattr(response, "content", "").strip()
        content = re.sub(r"^```(?:json)?|```$", "", content, flags=re.MULTILINE)
        match = re.search(r"\{.*\}", content, re.DOTALL)

        parsed = json.loads(match.group(0)) if match else {"AI Notes": content}
        logger.info(f"[PricingNode] 🧾 Final JSON: {parsed}")

        return {
            "messages": [response],
            "session_id": state["session_id"],
            "user_id": state["user_id"],
            "pricing_result": parsed,
            "tool_results": tool_data,
        }

    except Exception as e:
        logger.exception(f"[PricingNode] ❌ Error generating final JSON: {e}")
        return {
            "messages": state["messages"],
            "session_id": state["session_id"],
            "user_id": state["user_id"],
            "pricing_result": {"AI Notes": f"Error generating pricing: {e}"},
            "tool_results": tool_data,
        }
