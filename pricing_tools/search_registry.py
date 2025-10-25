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
from pricing_tools.search_mycomicshop import search_mycomicshop
from pricing_tools.discogs import search_discogs_tool
from pricing_tools.search_heritage import search_heritage
from pricing_tools.search_comicbookrealm import search_comicbookrealm
from pricing_tools.smart_search import smart_search

#Not currently used/helpful
#from pricing_tools.search_gocollect import search_gocollect

#useful, but slow
#from pricing_tools.search_gocollect_playwright_tool import search_gocollect_playwright_tool


# Optional: if you later re-enable Discogs or other sources, add them here.
# from pricing_tools.discogs import search_discogs

# The unified tool list the agent can use
ALL_SEARCH_TOOLS = [
    search_ebay,
    search_mycomicshop,
    search_discogs_tool,
    # search_heritage,
    # search_comicbookrealm,
    
    # smart_search,

    #Not currently used/helpful
    #search_gocollect,
    #search_gocollect_playwright_tool,
    #useful, but slow
]
