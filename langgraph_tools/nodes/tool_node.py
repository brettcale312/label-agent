"""
tool_node.py
-------------
Executes all tools selected by MarketNode.

Restores full functionality from the original PricingAgent `_tool_wrapper()`:
✅ Reads tool_calls from state (not messages)
✅ Executes async/sync tool functions concurrently
✅ Collects and logs detailed market stats
✅ Returns results in tool_results
✅ Keeps compatibility with LangGraph state flow
"""

import asyncio
import time
from typing import Dict, Any
from utils.logger import get_logger
from langgraph_tools.config.model_config import AGENT_MODE

logger = get_logger("tool_node")


# ---------------------------------------------------------------------
# Tool Node
# ---------------------------------------------------------------------
async def tool_node(state: Dict[str, Any], all_tools: list) -> Dict[str, Any]:
    """
    Executes the selected market/pricing tools concurrently
    and aggregates results for downstream nodes.
    """

    logger.info(f"[ToolNode] 🧰 Running tools under mode: {AGENT_MODE.upper()}")
    
    # -----------------------------------------------------------------
    # 1️⃣ Gather tool calls from state (new pattern)
    # -----------------------------------------------------------------
    tool_calls = state.get("tool_calls", [])
    if not tool_calls:
        logger.warning(f"[ToolNode] ⚠️ No tool calls found in state. Keys: {list(state.keys())}")
        return {
            **state,
            "tool_results": {},
        }

    # -----------------------------------------------------------------
    # 2️⃣ Define async tool executor
    # -----------------------------------------------------------------
    async def run_tool(tcall):
        tool_name = tcall.get("name")
        tool_args = tcall.get("args", {}) or {}
        tool_id = tcall.get("id")

        tool_func = next((t for t in all_tools if t.name == tool_name), None)
        if not tool_func:
            logger.warning(f"[ToolNode] ⚠️ Tool '{tool_name}' not registered.")
            return tool_id, {"status": "missing"}

        start = time.time()
        try:
            # Prefer async execution when supported
            if hasattr(tool_func, "arun"):
                result = await tool_func.arun(tool_args)
            elif hasattr(tool_func, "ainvoke"):
                result = await tool_func.ainvoke(tool_args)
            else:
                result = tool_func.run(tool_args)

            elapsed = round(time.time() - start, 2)

            # Log standard metrics if structured
            if isinstance(result, dict):
                src = result.get("source", tool_name)
                med = result.get("median") or result.get("median_price")
                avg = result.get("average") or result.get("average_price")
                count = result.get("samples") or result.get("sample_count")
                logger.info(
                    f"[{tool_name}] ✅ {src} | median={med} | avg={avg} | "
                    f"samples={count} | ⏱️ {elapsed}s"
                )
            else:
                logger.info(f"[{tool_name}] ✅ Completed in {elapsed}s (non-dict result)")

            return tool_id, result or {"status": "empty"}

        except Exception as e:
            logger.exception(f"[ToolNode] ❌ {tool_name} failed: {e}")
            return tool_id, {"status": "error", "message": str(e)}

    # -----------------------------------------------------------------
    # 3️⃣ Execute all selected tools concurrently
    # -----------------------------------------------------------------
    try:
        results = await asyncio.gather(*(run_tool(t) for t in tool_calls))
        tool_outputs = {tid: res for tid, res in results}
        logger.info(f"[ToolNode] ✅ Executed {len(tool_outputs)} tool(s) successfully")
    except Exception as e:
        logger.exception(f"[ToolNode] ❌ Concurrent execution failure: {e}")
        tool_outputs = {}

    # -----------------------------------------------------------------
    # 4️⃣ Normalize tool_results for downstream reasoning
    # -----------------------------------------------------------------
    # Flatten simple "price" or "median" keys to allow direct numeric access
    normalized = {}
    for tid, res in tool_outputs.items():
        if isinstance(res, dict):
            res = dict(res)
            if "median_price" in res and not res.get("median"):
                res["median"] = res["median_price"]
            if "average_price" in res and not res.get("average"):
                res["average"] = res["average_price"]
            normalized[tid] = res
        else:
            normalized[tid] = {"status": "invalid", "raw": str(res)}

    # -----------------------------------------------------------------
    # 5️⃣ Return updated agent state
    # -----------------------------------------------------------------
    return {
        **state,
        "tool_results": normalized,
    }
