"""
pricing_agent.py
----------------
LangGraph Pricing Agent (Persistent Context Version)

This orchestrator connects all modular nodes for AI-driven pricing:
1. VisionNode → extracts structured details (title, condition, category_hint)
2. MarketNode → selects pricing tools (eBay, Discogs, etc.)
3. ToolNode → executes those tools and collects market data
4. ReasoningNode → uses GPT to evaluate trust between sources
5. ValuationNode → applies deterministic math, multipliers, and rounding
6. ExplainNode → generates a human-readable reasoning summary

Now uses a persistent shared LLM context so that global rules and style
are loaded only once per session, significantly reducing per-item cost.
"""

import operator
from typing import Dict, Any, List, Optional, Annotated
from langgraph.graph import StateGraph, END
from typing_extensions import TypedDict
from utils.logger import get_logger

# ---------------------------------------------------------------------
# Modular Nodes
# ---------------------------------------------------------------------
from langgraph_tools.nodes.vision_node import vision_node
from langgraph_tools.nodes.market_node import market_node
from langgraph_tools.nodes.tool_node import tool_node
from langgraph_tools.nodes.reasoning_node import reasoning_node
from langgraph_tools.nodes.valuation_node import valuation_node
from langgraph_tools.nodes.explain_node import explain_node

# Shared context + tools + mode
from langgraph_tools.context.base_context import get_llm_context, reset_global_context
from pricing_tools.search_registry import ALL_SEARCH_TOOLS
from langgraph_tools.config.model_config import ACTIVE_MODE, AGENT_MODE

logger = get_logger("pricing_agent")


# ---------------------------------------------------------------------
# Agent State Schema
# ---------------------------------------------------------------------
class PricingAgentState(TypedDict):
    # Core conversational and session context
    messages: Annotated[List, operator.add]
    session_id: int
    user_id: str

    # Vision / item recognition
    current_item: Optional[Dict[str, Any]]

    # Tool orchestration
    tool_calls: Optional[List[Dict[str, Any]]]
    tool_results: Optional[Dict[str, Any]]

    # Reasoning + pricing pipeline
    market_data: Optional[Dict[str, Any]]
    reasoning: Optional[Dict[str, Any]]
    valuation: Optional[Dict[str, Any]]

    # High-level output / summary
    explanation: Optional[str]


# ---------------------------------------------------------------------
# PricingAgent Orchestrator
# ---------------------------------------------------------------------
class PricingAgent:
    """LangGraph agent for vision → market → tools → reasoning → valuation → explain."""

    def __init__(self):
        """Initialize agent with tools and persistent LLM context."""
        # Initialize persistent context once (loads BASE_CONTEXT, config, etc.)
        _ = get_llm_context()  # no positional arg anymore

        self.tools = ALL_SEARCH_TOOLS
        self.graph = self._create_graph()

        logger.info(
            f"[PricingAgent] 🚀 Initialized ({AGENT_MODE.upper()} mode) | "
            f"Vision={ACTIVE_MODE['vision']} | Market={ACTIVE_MODE['market']} | Pricing={ACTIVE_MODE['pricing']}"
        )
        logger.info(f"[PricingAgent] 🔧 Registered {len(self.tools)} tools: {[t.name for t in self.tools]}")

    # -----------------------------------------------------------------
    def _create_graph(self):
        """Build and compile the LangGraph pipeline."""
        g = StateGraph(PricingAgentState)

        # --- Define nodes ---
        g.add_node("vision_agent", vision_node)
        g.add_node("market_agent", market_node)

        # Wrap modular tool node with tool list
        async def tool_wrapper(state):
            return await tool_node(state, self.tools)

        g.add_node("tools", tool_wrapper)
        g.add_node("reasoning_agent", reasoning_node)
        g.add_node("valuation_agent", valuation_node)
        g.add_node("explain_agent", explain_node)

        # --- Define flow ---
        g.set_entry_point("vision_agent")
        g.add_edge("vision_agent", "market_agent")
        g.add_edge("market_agent", "tools")
        g.add_edge("tools", "reasoning_agent")
        g.add_edge("reasoning_agent", "valuation_agent")
        g.add_edge("valuation_agent", "explain_agent")
        g.add_edge("explain_agent", END)

        logger.info("[PricingAgent] 🔗 Graph compiled successfully.")
        return g.compile()


# ---------------------------------------------------------------------
# Optional: Standalone Runner
# ---------------------------------------------------------------------
if __name__ == "__main__":
    import os
    from pprint import pprint
    from langgraph_tools.session_utils import price_item_from_image

    # 🔄 Reset context at start of each test run
    reset_global_context()

    agent = PricingAgent()

    test_path = os.path.join(os.getcwd(), "test_record.jpg")
    if not os.path.exists(test_path):
        print("⚠️  No test image found (expected test_record.jpg in working directory).")
    else:
        with open(test_path, "rb") as f:
            result = price_item_from_image(
                agent.graph,
                user_id="local_test",
                image_bytes=f.read(),
                item_type="record"
            )

        print("\n✅ FINAL RESULT:\n")
        pprint(result)
