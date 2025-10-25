"""
explain_node.py
---------------
Generates a natural-language explanation of the final pricing decision.
"""

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from utils.logger import get_logger

logger = get_logger("explain_node")

@tool("explain_node")
async def explain_node_tool(context: dict) -> str:
    """
    Summarize the pricing logic for human readability.
    """
    llm = ChatOpenAI(model="gpt-4o", temperature=0.5)
    prompt = f"""
    Explain the following pricing decision clearly for a vendor report:
    {context}

    Focus on:
    - Which source influenced the price most
    - Any adjustments (venue, condition)
    - Final estimated value and reasoning
    """
    try:
        response = await llm.ainvoke(prompt)
        logger.info(f"[ExplainNode] Summary: {response}")
        return response
    except Exception as e:
        logger.error(f"[ExplainNode] Error: {e}")
        return f"Explanation unavailable: {e}"
