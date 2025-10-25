"""
LangGraph Pricing Agent — 4-stage pipeline with structured vision output and intelligent tool selection.
---------------------------------------------------------------------------------------
1. Vision Node → identifies item from image (structured with Pydantic)
2. Market Node → decides which tools to call (eBay, Discogs, etc.)
3. Tool Node → executes selected tools
4. Pricing Node → merges recognition + tool data into structured JSON
"""

import os, shutil, tempfile

# ---------------------------------------------------------------------
# DEV-MODE CACHE FLUSH
# ---------------------------------------------------------------------
if os.getenv("RESET_AGENT_CACHE", "0") == "1":
    for p in [
        ".langgraph_cache",
        ".langchain",
        os.path.join(tempfile.gettempdir(), "langgraph"),
        os.path.join(os.getenv("LOCALAPPDATA", ""), "langgraph"),
    ]:
        try:
            if p and os.path.exists(p):
                shutil.rmtree(p, ignore_errors=True)
        except Exception:
            pass

import base64, io, json, operator, re, asyncio, nest_asyncio, logging
from typing import Dict, Any, List, Optional, Annotated
from PIL import Image
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from pydantic import BaseModel, Field
from typing_extensions import TypedDict
from langchain_openai import ChatOpenAI

from database.connection import get_db_session
from database.operations import PricingSessionOps
from pricing_tools.search_registry import ALL_SEARCH_TOOLS
from schemas.pricing_schemas import get_schema
from utils.logger import get_logger

# ---------------------------------------------------------------------
# Noise reduction for libraries
# ---------------------------------------------------------------------
for lib in ["httpx", "openai", "langchain", "urllib3", "sqlalchemy"]:
    logging.getLogger(lib).setLevel(logging.WARNING)

nest_asyncio.apply()
logger = get_logger(__name__)

# ---------------------------------------------------------------------
# Structured Vision Output
# ---------------------------------------------------------------------
class VisionOutput(BaseModel):
    title: str = Field(..., description="Title or name of the item.")
    issue_number: Optional[str] = None
    publisher: Optional[str] = None
    condition: Optional[str] = None
    notable_attributes: List[str] = []
    raw_summary: Optional[str] = None

# ---------------------------------------------------------------------
# LangGraph State
# ---------------------------------------------------------------------
class PricingAgentState(TypedDict):
    messages: Annotated[List, operator.add]
    session_id: int
    user_id: str
    current_item: Optional[Dict[str, Any]]
    pricing_result: Optional[Dict[str, Any]]
    tool_results: Optional[Dict[str, Any]]

# ---------------------------------------------------------------------
# PricingAgent
# ---------------------------------------------------------------------
class PricingAgent:
    """4-node LangGraph agent for vision → market → tools → pricing."""

    def __init__(self, model_name: str = "gpt-4o-mini"):
        self.model = ChatOpenAI(model=model_name, temperature=0.2)
        self.vision_model = ChatOpenAI(model=model_name, temperature=0.2).with_structured_output(VisionOutput)
        self.tools = ALL_SEARCH_TOOLS
        self.tool_node = ToolNode(self.tools)
        self.graph = self._create_graph()
        logger.info(f"[PricingAgent] Initialized with model {model_name} and {len(self.tools)} tools: {[t.name for t in self.tools]}")

    # -----------------------------------------------------------------
    def _create_graph(self) -> StateGraph:
        g = StateGraph(PricingAgentState)
        g.add_node("vision_agent", self._vision_node)
        g.add_node("market_agent", self._market_node)
        
        # -----------------------------------------------------------------
        # TOOL WRAPPER  (clean logging version)
        # -----------------------------------------------------------------
        async def _tool_wrapper(state: PricingAgentState) -> Dict[str, Any]:
            """Executes selected tools and maps results to tool_call_ids with compact logs."""
            tool_calls = []
            for msg in state["messages"]:
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    tool_calls.extend(msg.tool_calls)

            tool_outputs: Dict[str, Any] = {}

            for tcall in tool_calls:
                tool_name = tcall.get("name")
                tool_args = tcall.get("args", {})
                tool_id = tcall.get("id")
                tool_func = next((t for t in self.tools if t.name == tool_name), None)

                if not tool_func:
                    logger.warning(f"[ToolNode] ⚠️ Tool {tool_name} not found in registry.")
                    tool_outputs[tool_id] = {"status": "missing"}
                    continue

                try:
                    # Run async or sync
                    if hasattr(tool_func, "arun"):
                        result = await tool_func.arun(tool_args)
                    elif hasattr(tool_func, "run"):
                        result = tool_func.run(tool_args)
                    else:
                        logger.warning(f"[ToolNode] ⚠️ Tool {tool_name} has no run/arun method.")
                        result = None

                    # --- Smart summarized logging ---
                    if isinstance(result, dict):
                        src = result.get("source", tool_name)
                        med = result.get("median_price")
                        avg = result.get("average_price")
                        count = result.get("sample_count")
                        summary = f"[{tool_name}] {src} | median={med} | avg={avg} | samples={count}"
                        logger.info(summary)

                        # Log a trimmed JSON for file logs only (no console spam)
                        trimmed = {k: v for k, v in result.items() if k not in ("raw", "items", "raw_prices")}
                        if logger.handlers:
                            logger.debug(f"[ToolNode DEBUG] {tool_name} result: {json.dumps(trimmed)[:400]}...")

                    else:
                        logger.info(f"[{tool_name}] result: {result}")

                    tool_outputs[tool_id] = result or {"status": "empty"}

                except Exception as e:
                    logger.exception(f"[ToolNode] ❌ {tool_name} failed: {e}")
                    tool_outputs[tool_id] = {"status": "error", "message": str(e)}

            logger.info(f"[ToolNode] ✅ Executed {len(tool_outputs)} tools")
            return {
                "messages": state["messages"],
                "session_id": state["session_id"],
                "user_id": state["user_id"],
                "current_item": state.get("current_item"),
                "tool_results": tool_outputs,
            }


        g.add_node("tools", _tool_wrapper)
        g.add_node("pricing_agent", self._pricing_node)
        g.set_entry_point("vision_agent")
        g.add_edge("vision_agent", "market_agent")
        g.add_edge("market_agent", "tools")
        g.add_edge("tools", "pricing_agent")
        g.add_edge("pricing_agent", END)
        return g.compile()

    # -----------------------------------------------------------------
    # Vision Node
    # -----------------------------------------------------------------
    def _vision_node(self, state: PricingAgentState) -> Dict[str, Any]:
        item_type = state.get("current_item", {}).get("type", "item")
        vision_prompt = f"""
You are an expert at identifying collectibles from images.
Describe the following {item_type} with structured detail:
- title
- issue number
- publisher or brand
- condition
- notable attributes
Include a short raw_summary.
"""
        messages = [SystemMessage(content=vision_prompt)] + state["messages"]
        try:
            vision_output: VisionOutput = self.vision_model.invoke(messages)
            ai_msg = AIMessage(content=f"Structured vision output: {vision_output.model_dump_json(indent=2)}")
        except Exception as e:
            logger.error(f"[VisionNode] ❌ Vision structured output failed: {e}")
            response = self.model.invoke(messages)
            ai_msg = AIMessage(content=getattr(response, "content", "").strip())
            vision_output = None

        current_item = {"type": item_type}
        if vision_output:
            current_item.update({
                "title": vision_output.title,
                "issue_number": vision_output.issue_number,
                "publisher": vision_output.publisher,
                "condition": vision_output.condition,
                "attributes": vision_output.notable_attributes,
                "vision_summary": vision_output.raw_summary or vision_output.model_dump_json(indent=2),
            })
        else:
            current_item["vision_summary"] = ai_msg.content

        logger.info(f"[VisionNode] ✅ {current_item.get('title','(unknown)')} | {current_item.get('condition','')}")
        return {
            "messages": state["messages"] + [ai_msg],
            "session_id": state["session_id"],
            "user_id": state["user_id"],
            "current_item": current_item,
        }

    # -----------------------------------------------------------------
    # Market Node
    # -----------------------------------------------------------------
    def _market_node(self, state: PricingAgentState) -> Dict[str, Any]:
        current_item = state.get("current_item", {}) or {}
        title = current_item.get("title", "")
        issue = current_item.get("issue_number", "")
        condition = current_item.get("condition", "")
        attributes = ", ".join(current_item.get("attributes", []))

        market_prompt = f"""
You are the market intelligence model for collectibles.
Based on the following item info, decide which pricing tools to use.
Item: "{title} {issue}" ({condition}) [{attributes}]

Available tools:
search_ebay, search_mycomicshop

Respond ONLY with tool call syntax, one per line:
search_ebay("Spider-Man #31 Near Mint variant cover")
search_mycomicshop("Spider-Man #31 Near Mint variant cover")
"""
        response = self.model.invoke([SystemMessage(content=market_prompt)])
        text = getattr(response, "content", "").strip()

        matches = re.findall(r"(\w+)\((?:\"|')?([^\"'\)]+)(?:\"|')?\)", text)
        tool_calls = [{"name": n, "args": {"query": q}, "id": f"toolu_{i+1}"} for i, (n, q) in enumerate(matches)] \
                     or [{"name": "search_ebay", "args": {"query": f"{title} {issue} {condition} {attributes}".strip()}, "id": "toolu_1"}]

        logger.info(f"[MarketNode] 🧩 Selected tools: {', '.join(t['name'] for t in tool_calls)}")
        response.tool_calls = tool_calls
        return {
            "messages": state["messages"] + [response],
            "session_id": state["session_id"],
            "user_id": state["user_id"],
            "current_item": current_item,
        }

    # -----------------------------------------------------------------
    # PRICING NODE (compact summary logging)
    # -----------------------------------------------------------------
    def _pricing_node(self, state: PricingAgentState) -> Dict[str, Any]:
        type_ = state.get("current_item", {}).get("type", "anything").lower()
        structure = get_schema(type_)
        tool_data = state.get("tool_results", {}) or {}
        current_item = state.get("current_item", {}) or {}

        # --- Compact summaries only ---
        summaries = []
        for v in tool_data.values():
            if isinstance(v, dict):
                src = v.get("source")
                med = v.get("median_price")
                avg = v.get("average_price")
                count = v.get("sample_count")
                summaries.append(f"{src}: median={med}, avg={avg}, samples={count}")
        if summaries:
            logger.info("[PricingNode] 🔧 " + " | ".join(summaries))

        # --- Derive Base_Price ---
        base_price = None
        for v in tool_data.values():
            if isinstance(v, dict):
                for val in v.values():
                    if isinstance(val, (int, float)) and val > 0:
                        base_price = val; break
                    if isinstance(val, str) and val.replace('.', '', 1).isdigit():
                        base_price = float(val); break
            if base_price: break

        if base_price:
            current_item["Base_Price"] = base_price
            logger.info(f"[PricingNode] 💵 Base_Price: {base_price}")
        else:
            logger.info("[PricingNode] ⚠️ No numeric Base_Price detected.")

        # --- Build clean message chain ---
        tool_messages = [{"role": "tool", "tool_call_id": k, "content": json.dumps(v, indent=2)} for k, v in tool_data.items()]
        first_human = next((m for m in state["messages"] if isinstance(m, HumanMessage)), None)
        last_tool_msg = next((m for m in reversed(state["messages"]) if isinstance(m, AIMessage) and getattr(m, "tool_calls", None)), None)

        messages = [SystemMessage(content="You are a pricing agent synthesizing tool data and vision recognition results.")]
        if first_human: messages.append(first_human)
        if last_tool_msg: messages.append(last_tool_msg)
        messages.extend(tool_messages)

        context = {
            "comic": "You are an expert in comic book pricing; include 3 concise bullets.",
            "card": "You are an expert in trading card valuation; include 2 concise bullets.",
            "record": "You are an expert in vinyl record valuation; include label, pressing, and year.",
        }.get(type_, "You are an expert appraiser.")

        pricing_prompt = f"""
    You have recognition data and summarized tool results.

    Recognition data:
    {json.dumps(current_item, indent=2)}

    Output ONLY valid JSON using this schema:
    {json.dumps(structure, indent=2)}

    Rules:
    - Fill all fields.
    - Base_Price = median/lowest from tools.
    - Price includes condition markup.
    - Include reasoning in 'AI Notes'.
    {context}
    """
        messages.append(SystemMessage(content=pricing_prompt))

        # --- Invoke model ---
        response = self.model.invoke(messages)
        content = re.sub(r"^```(?:json)?|```$", "", getattr(response, "content", "").strip(), flags=re.MULTILINE)
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

    # -----------------------------------------------------------------
    # Session helpers
    # -----------------------------------------------------------------
    def create_session(self, user_id: str, session_name: Optional[str] = None) -> int:
        db = get_db_session()
        try:
            session = PricingSessionOps.create_session(db, user_id, session_name)
            logger.info(f"[PricingAgent] Created session {session.id} for {user_id}")
            return session.id
        finally:
            db.close()

    def get_or_create_session(self, user_id: str) -> int:
        db = get_db_session()
        try:
            session = PricingSessionOps.get_active_session(db, user_id)
            if session:
                logger.info(f"[PricingAgent] Using existing session {session.id} for {user_id}")
                return session.id
            return self.create_session(user_id)
        finally:
            db.close()

    # -----------------------------------------------------------------
    def price_item_from_image(self, user_id: str, image_bytes: bytes, item_type: str) -> Dict[str, Any]:
        """Runs full recognition → market decision → tool lookup → pricing reasoning."""
        try:
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            image.thumbnail((1024, 1024))
            buf = io.BytesIO()
            image.save(buf, format="JPEG", quality=85)
            image_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

            session_id = self.get_or_create_session(user_id)
            messages = [HumanMessage(content=[{"type": "text", "text": f"Please analyze and price this {item_type}."},
                                              {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}])]
            state = {"messages": messages, "session_id": session_id, "user_id": user_id, "current_item": {"type": item_type}}

            result = asyncio.run(self.graph.ainvoke(state))
            parsed = result.get("pricing_result", {})
            tool_data = result.get("tool_results", {})
            logger.info(f"[PricingAgent] ✅ Full pipeline complete.")
            return {"success": True, "pricing_result": parsed, "tool_results": tool_data, "session_id": session_id}

        except Exception as e:
            logger.error(f"[PricingAgent] Error in price_item_from_image: {e}")
            return {"success": False, "error": str(e)}
