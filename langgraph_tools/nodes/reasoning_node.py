"""
reasoning_node.py
-----------------
Uses GPT-5 to interpret pricing data and assign source weights.
"""

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from utils.logger import get_logger

logger = get_logger("reasoning_node")

@tool("reasoning_node")
async def reasoning_node_tool(market_data: dict) -> dict:
    """
    Given eBay and Discogs results, determine relative reliability.
    Output: {"ebay_weight": 0.7, "discogs_weight": 0.3, "comment": "..."}
    """
    llm = ChatOpenAI(model="gpt-5", temperature=0.3)

    prompt = f"""
    You are an expert appraiser.
    Analyze this market data and assign weights to each source for pricing.
    Data:
    {market_data}

    Rules of thumb:
    - eBay reflects current market demand.
    - Discogs is a historical reference, often low for common items.
    - If Discogs median < half of eBay median, reduce Discogs weight.
    - If Discogs has higher median and large sample count, trust more.

    Respond in pure JSON:
    {{
        "ebay_weight": float,
        "discogs_weight": float,
        "comment": "string summary"
    }}
    """
    try:
        response = await llm.ainvoke(prompt)
        logger.info(f"[ReasoningNode] Output: {response}")
        return response
    except Exception as e:
        logger.error(f"[ReasoningNode] Error: {e}")
        return {"error": str(e)}
