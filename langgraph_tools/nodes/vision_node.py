"""
vision_node.py
--------------
Optional node that extracts title, artist, and condition from an image
or metadata blob using GPT-5-Vision.
"""

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from utils.logger import get_logger

logger = get_logger("vision_node")

@tool("vision_node")
async def vision_node_tool(image_description: str) -> dict:
    """
    Extract structured metadata (title, artist, category, condition)
    from an image caption or description.
    """
    llm = ChatOpenAI(model="gpt-5-vision", temperature=0.2)
    prompt = f"""
    Analyze the following item description and extract fields:
    - title
    - artist / creator
    - category (record, comic, card, etc.)
    - condition (sealed, NM, VG, G)
    - any edition or pressing clues

    Description:
    {image_description}
    """
    try:
        result = await llm.ainvoke(prompt)
        logger.info(f"[VisionNode] Parsed metadata: {result}")
        return {"source": "Vision", "data": result}
    except Exception as e:
        logger.error(f"[VisionNode] Error: {e}")
        return {"source": "Vision", "error": str(e)}
