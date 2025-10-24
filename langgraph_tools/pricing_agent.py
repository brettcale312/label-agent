"""
LangGraph Pricing Agent — 4-stage pipeline with structured vision output and intelligent tool selection.
---------------------------------------------------------------------------------------
1. Vision Node → identifies item from image (structured with Pydantic)
2. Market Node → decides which tools to call (eBay, Discogs, etc.)
3. Tool Node → executes selected tools
4. Pricing Node → merges recognition + tool data into structured JSON
"""

import base64, io, json, operator, re, asyncio, nest_asyncio
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

        async def _tool_wrapper(state: PricingAgentState) -> Dict[str, Any]:
            """Executes selected tools and maps results to tool_call_ids."""
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
                    tool_outputs[tool_id] = {"status": "missing", "message": f"Tool {tool_name} not found."}
                    continue

                try:
                    # Proper StructuredTool invocation
                    if hasattr(tool_func, "arun"):
                        result = await tool_func.arun(tool_args)
                    elif hasattr(tool_func, "run"):
                        result = tool_func.run(tool_args)
                    else:
                        logger.warning(f"[ToolNode] ⚠️ Tool {tool_name} has no run/arun method.")
                        result = None

                    logger.info(f"[ToolNode] ✅ Tool {tool_name} returned: {result}")
                    tool_outputs[tool_id] = result or {"status": "empty", "message": "No data returned."}

                except Exception as e:
                    logger.exception(f"[ToolNode] ❌ Tool {tool_name} failed: {e}")
                    tool_outputs[tool_id] = {"status": "error", "message": str(e)}

            logger.info(f"[ToolNode] ✅ Executed {len(tool_outputs)} tools, mapped results to IDs")
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
- issue number (if applicable)
- publisher or brand
- condition (mint, near mint, etc.)
- notable attributes (variant, first appearance, holofoil, etc.)
Also include a short raw_summary of what you see.
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

        if vision_output:
            current_item = {
                "type": item_type,
                "title": vision_output.title,
                "issue_number": vision_output.issue_number,
                "publisher": vision_output.publisher,
                "condition": vision_output.condition,
                "attributes": vision_output.notable_attributes,
                "vision_summary": vision_output.raw_summary or vision_output.model_dump_json(indent=2),
            }
        else:
            current_item = {"type": item_type, "vision_summary": ai_msg.content}

        logger.info(f"[VisionNode] ✅ Structured output:\n{ai_msg.content}")
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
Based on the following item info, decide which pricing data tools to use.
Item: "{title} {issue}" ({condition}) [{attributes}]

Available tools:
search_ebay

Respond ONLY with valid tool call syntax, one per line:
search_ebay("Amazing Spider-Man #31 Near Mint variant cover")

"""
#,search_heritage, search_comicbookrealm, search_gocollect, smart_search
#search_gocollect("Amazing Spider-Man #31 Near Mint variant cover")
        response = self.model.invoke([SystemMessage(content=market_prompt)])
        logger.info(f"[MarketNode] 🧠 Tool decision message: {response}")

        tool_calls = []
        if hasattr(response, "tool_calls") and response.tool_calls:
            tool_calls = response.tool_calls
        else:
            text = getattr(response, "content", "").strip()
            matches = re.findall(r"(\w+)\((?:\"|')?([^\"'\)]+)(?:\"|')?\)", text)
            if matches:
                for name, query in matches:
                    tool_calls.append({"name": name, "args": {"query": query}})
            else:
                query = f"{title} {issue} {condition} {attributes}".strip()
                tool_calls = [{"name": "search_ebay", "args": {"query": query}}]

        for i, t in enumerate(tool_calls, start=1):
            t.setdefault("id", f"toolu_{i}")

        response.tool_calls = tool_calls
        logger.info(f"[MarketNode] 🧩 Normalized tool calls with IDs: {json.dumps(tool_calls, indent=2)}")

        return {
            "messages": state["messages"] + [response],
            "session_id": state["session_id"],
            "user_id": state["user_id"],
            "current_item": current_item,
        }

        # -----------------------------------------------------------------
    # Pricing Node (FINAL VERSION with Base_Price injection)
    # -----------------------------------------------------------------
    def _pricing_node(self, state: PricingAgentState) -> Dict[str, Any]:
        type_ = state.get("current_item", {}).get("type", "anything").lower()
        structure = get_schema(type_)
        tool_data = state.get("tool_results", {}) or {}
        current_item = state.get("current_item", {}) or {}

        logger.info(f"[PricingNode] 🔧 Received tool data: {json.dumps(tool_data, indent=2)}")

        # Find the last AIMessage with tool_calls (the model that triggered the tools)
        last_tool_msg = None
        for msg in reversed(state["messages"]):
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                last_tool_msg = msg
                break

        # --- Convert tool_data into proper OpenAI tool messages ---
        tool_messages = []
        for tool_id, result in tool_data.items():
            tool_messages.append({
                "role": "tool",
                "tool_call_id": tool_id,
                "content": json.dumps(result, indent=2)
            })

        # --- Build a clean, valid message chain ---
        clean_messages = []
        clean_messages.append(SystemMessage(content="You are a pricing agent synthesizing tool data and vision recognition results."))
        first_human = next((m for m in state["messages"] if isinstance(m, HumanMessage)), None)
        if first_human:
            clean_messages.append(first_human)
        if last_tool_msg:
            clean_messages.append(last_tool_msg)
        for tm in tool_messages:
            clean_messages.append(tm)

        # --- Try to derive a Base_Price from any tool output ---
        base_price = None
        for k, v in tool_data.items():
            if isinstance(v, dict):
                # Search for numeric-looking values in tool outputs
                for key, val in v.items():
                    if isinstance(val, (int, float)) and val > 0:
                        base_price = val
                        break
                    elif isinstance(val, str) and val.replace('.', '', 1).isdigit():
                        base_price = float(val)
                        break
            elif isinstance(v, (int, float)) and v > 0:
                base_price = v

        if base_price:
            current_item["Base_Price"] = base_price
            logger.info(f"[PricingNode] 💵 Injected Base_Price from tools: {base_price}")
        else:
            logger.info("[PricingNode] ⚠️ No numeric Base_Price detected in tool results.")

        # --- Diagnostic log of message order ---
        seq = []
        for m in clean_messages:
            if hasattr(m, "role"):
                seq.append(m.role)
            elif isinstance(m, dict):
                seq.append(m.get("role", "?"))
            else:
                seq.append(type(m).__name__)
        logger.info(f"[PricingNode] 🧩 Message order before invoke: {seq}")

        # --- Pricing reasoning prompt ---
        context = "You are an expert appraiser."
        if type_ == "comic":
            context = "You are an expert in comic book pricing; include 3 concise bullets."
        elif type_ == "card":
            context = "You are an expert in trading card valuation; include 2 concise bullets."
        elif type_ == "record":
            context = "You are an expert in vinyl record valuation; include label, pressing, and year."

        pricing_prompt = f"""
You have recognition data and market tool results.

Recognition data:
{json.dumps(current_item, indent=2)}

Tool data:
{json.dumps(tool_data, indent=2)}

Output ONLY valid JSON using this schema:
{json.dumps(structure, indent=2)}

Rules:
- Fill all fields.
- Base_Price = tool median or lowest.
- Price includes markup for condition.
- Include reasoning in 'AI Notes'.
- Do not include commentary or introductions before or after JSON.
{context}
"""
        clean_messages.append(SystemMessage(content=pricing_prompt))

        # --- Call the model with the cleaned message chain ---
        response = self.model.invoke(clean_messages)
        content = getattr(response, "content", "").strip()
        content = re.sub(r"^```(?:json)?|```$", "", content, flags=re.MULTILINE).strip()
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            content = match.group(0)

        try:
            parsed = json.loads(content)
        except Exception as e:
            logger.warning(f"[PricingNode] ⚠️ Could not parse JSON directly: {e}")
            parsed = {"Title_Issue": "Unrecognized item", "AI Notes": content}

        logger.info(f"[PricingNode] 🧾 Final JSON output: {parsed}")
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
            logger.info(f"[PricingAgent] Created new session {session.id} for {user_id}")
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
            messages = [
                HumanMessage(
                    content=[
                        {"type": "text", "text": f"Please analyze and price this {item_type}."},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}
                    ]
                )
            ]
            state = {
                "messages": messages,
                "session_id": session_id,
                "user_id": user_id,
                "current_item": {"type": item_type},
            }

            result = asyncio.run(self.graph.ainvoke(state))
            parsed = result.get("pricing_result", {})
            tool_data = result.get("tool_results", {})

            logger.info(f"[PricingAgent] ✅ Full pipeline complete.")
            return {"success": True, "pricing_result": parsed, "tool_results": tool_data, "session_id": session_id}

        except Exception as e:
            logger.error(f"[PricingAgent] Error in price_item_from_image: {e}")
            return {"success": False, "error": str(e)}
