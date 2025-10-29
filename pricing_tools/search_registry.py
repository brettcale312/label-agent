"""
search_registry.py
------------------
Centralized registry of all search-related tools for the Market Agent.

Import this list wherever you initialize your LangGraph or LangChain agents:
    from pricing_tools.search_registry import ALL_SEARCH_TOOLS

Then pass it to your agent initialization:
    agent = initialize_agent(ALL_SEARCH_TOOLS, llm, ...)

This ensures all active market data sources are consistently available.
"""

from pricing_tools.ebay import search_ebay
from pricing_tools.search_pricecharting_tool import search_pricecharting_tool
from pricing_tools.search_mycomicshop import search_mycomicshop
from pricing_tools.discogs import search_discogs_tool
from pricing_tools.smart_search import smart_search
from pricing_tools.search_keepa_tool import search_keepa_tool
from pricing_tools.search_keepa_smart_tool import search_keepa_smart_tool

# The unified tool list the agent can use
ALL_SEARCH_TOOLS = [
    search_ebay,
    search_mycomicshop,
    search_discogs_tool,
    search_keepa_tool,
    search_keepa_smart_tool,
    search_pricecharting_tool,
    smart_search,
]
