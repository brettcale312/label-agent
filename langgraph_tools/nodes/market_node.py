"""
market_node.py
---------------
Fetches market data from eBay and Discogs concurrently.
"""

import asyncio
from pricing_tools.ebay import search_ebay_tool
from pricing_tools.discogs import search_discogs_tool
from utils.logger import get_logger

logger = get_logger("market_node")

async def market_node(query: str) -> dict:
    """Run eBay and Discogs lookups in parallel."""
    logger.info(f"[MarketNode] Searching for '{query}'")
    try:
        ebay_task = asyncio.create_task(search_ebay_tool(query))
        discogs_task = asyncio.create_task(search_discogs_tool(query))
        ebay_result, discogs_result = await asyncio.gather(ebay_task, discogs_task)

        return {"ebay": ebay_result, "discogs": discogs_result}
    except Exception as e:
        logger.error(f"[MarketNode] Error: {e}")
        return {"error": str(e)}
