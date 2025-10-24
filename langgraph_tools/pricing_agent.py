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
from langgraph_tools.pricing_tools import pricing_tools
from schemas.pricing_schemas import get_schema
from utils.logger import get_logger

nest_asyncio.apply()

try:
    from pricing_tools.ebay import search_ebay
except Exception:
    search_ebay = None

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
        self.tools = pricing_tools
        self.tool_node = ToolNode(self.tools)
        self.graph = self._create_graph()
        logger.info(f"[PricingAgent] Initialized with model {model_name}")

    # -----------------------------------------------------------------
    def _create_graph(self) -> StateGraph:
        g = StateGraph(PricingAgentState)
        g.add_node("vision_agent", self._vision_node)
        g.add_node("market_agent", self._market_node)
        g.add_node("tools", self.tool_node)
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
    # Market Node (decides which tools to use)
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
Respond ONLY with tool call syntax, e.g.:
search_ebay("Amazing Spider-Man #31 Near Mint variant cover")
You may chain multiple tools by listing them, one per line.
"""

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

        # Add unique IDs (required by ToolNode)
        for i, t in enumerate(tool_calls, start=1):
            if "id" not in t:
                t["id"] = f"toolu_{i}"

        response.tool_calls = tool_calls
        logger.info(f"[MarketNode] 🧩 Normalized tool calls with IDs: {json.dumps(tool_calls, indent=2)}")

        return {
            "messages": state["messages"] + [response],
            "session_id": state["session_id"],
            "user_id": state["user_id"],
            "current_item": current_item,
        }

    # -----------------------------------------------------------------
    # Pricing Node (final reasoning & JSON output)
    # -----------------------------------------------------------------
    def _pricing_node(self, state: PricingAgentState) -> Dict[str, Any]:
        type_ = state.get("current_item", {}).get("type", "anything").lower()
        structure = get_schema(type_)
        tool_data = state.get("tool_results", {}) or {}
        current_item = state.get("current_item", {}) or {}

        logger.info(f"[PricingNode] 🔧 Received tool data: {json.dumps(tool_data, indent=2)}")

        # Context and rules
        context = "You are an expert appraiser."
        if type_ == "comic":
            context = "You are an expert in comic book pricing; include 3 concise bullets."
        elif type_ == "card":
            context = "You are an expert in trading card valuation; include 2 concise bullets."
        elif type_ == "record":
            context = "You are an expert in vinyl records; include label, pressing, year."

        market_context = ""
        if "eBay" in tool_data:
            eb = tool_data["eBay"]
            median, avg, count = eb.get("median_price"), eb.get("average_price"), eb.get("sample_count")
            if median or avg:
                market_context = f"\n\nMarket data: eBay median ${median or '?'} (avg ${avg or '?'}) from {count or '?'} listings."

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
{market_context}
{context}
"""

        messages = [SystemMessage(content=pricing_prompt)] + state["messages"]
        response = self.model.invoke(messages)
        content = getattr(response, "content", "").strip()

        # 🧼 Clean markdown fences and stray text
        content = re.sub(r"^```(?:json)?|```$", "", content, flags=re.MULTILINE).strip()

        # 🧩 Extract inner JSON if wrapped in prose
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
    # Session Helpers
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
    # Entry Point
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

            result = self.graph.invoke(state)
            parsed = result.get("pricing_result", {})
            tool_data = result.get("tool_results", {})

            logger.info(f"[PricingAgent] ✅ Full pipeline complete.")
            return {"success": True, "pricing_result": parsed, "tool_results": tool_data, "session_id": session_id}

        except Exception as e:
            logger.error(f"[PricingAgent] Error in price_item_from_image: {e}")
            return {"success": False, "error": str(e)}
