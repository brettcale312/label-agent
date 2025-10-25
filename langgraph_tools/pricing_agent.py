"""
LangGraph Pricing Agent — 4-stage pipeline with structured vision output and intelligent tool selection.
---------------------------------------------------------------------------------------
1. Vision Node → identifies item from image (structured with JSON, returns category_hint)
2. Market Node → decides which tools to call (eBay, MyComicShop, etc.)
3. Tool Node → executes selected tools
4. Pricing Node → merges recognition + tool data into structured JSON, applies artist premiums
"""

import os, shutil, tempfile, base64, io, json, operator, re, asyncio, nest_asyncio, logging
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
from pricing_tools.valuation_logic import ARTIST_PREMIUMS
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
# Vision JSON Schema Output
# ---------------------------------------------------------------------
class VisionOutput(BaseModel):
    title: str
    issue_number: Optional[str] = None
    publisher: Optional[str] = None
    condition: Optional[str] = None
    notable_attributes: List[str] = []
    raw_summary: Optional[str] = None


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
        self.tools = ALL_SEARCH_TOOLS
        self.tool_node = ToolNode(self.tools)
        self.graph = self._create_graph()
        logger.info(
            f"[PricingAgent] Initialized with model {model_name} and {len(self.tools)} tools: "
            f"{[t.name for t in self.tools]}"
        )

    # -----------------------------------------------------------------
    def _create_graph(self) -> StateGraph:
        g = StateGraph(PricingAgentState)
        g.add_node("vision_agent", self._vision_node)
        g.add_node("market_agent", self._market_node)
        g.add_node("tools", self._tool_wrapper)
        g.add_node("pricing_agent", self._pricing_node)
        g.set_entry_point("vision_agent")
        g.add_edge("vision_agent", "market_agent")
        g.add_edge("market_agent", "tools")
        g.add_edge("tools", "pricing_agent")
        g.add_edge("pricing_agent", END)
        return g.compile()

    # -----------------------------------------------------------------
    # Vision Node (Advanced Structured)
    # -----------------------------------------------------------------
    def _vision_node(self, state: PricingAgentState) -> Dict[str, Any]:
        item_type = state.get("current_item", {}).get("type", "item")

        detailed_prompt = """
You are a professional collectibles grader and catalog specialist.
Examine the image carefully and extract **all visible structured details**.
Identify the collectible precisely — aim to distinguish between editions, variants, or printings.

Respond in structured JSON with the following fields:

{
  "item_type": "comic | trading_card | vinyl_record | toy | other",
  "title": "",
  "series": "",
  "issue_number": "",
  "legacy_number": "",
  "variant_type": "",
  "publisher_or_brand": "",
  "release_year": "",
  "barcode_or_isbn": "",
  "cover_artist_or_label": "",
  "notable_characters": "",
  "key_issue_details": "",
  "rarity_or_limited_info": "",
  "condition_estimate": "",
  "visual_notes": "",
  "raw_summary": ""
}

### Enhanced Comic-Specific Rules ###
- Detect and output "cover_artist_or_label" (e.g., Rob Liefeld, Alex Ross, J. Scott Campbell).
- Include any anniversary or event logos (e.g., 50 Years, Fall of X).
- If a barcode block is visible, extract its numeric code.
- Estimate release_year from indicia or barcode pattern.
- Note any visible creator signatures on the cover (e.g., “Liefeld”, “McFarlane”).
- Grade visible condition cues (spine wear, corner dents, gloss loss).

**For Trading Cards:**
- Include game/series name, card number, rarity, and edition (1st Edition, Unlimited, Promo).
- Note holofoil, reverse holo, or alternate art.

**For Vinyl Records:**
- Include artist, album, label, catalog number, pressing details.

**General Rules:**
- Include every visible printed code (barcode, catalog, LGY, etc.)
- Keep `raw_summary` to 2 sentences summarizing what you see.
"""

        messages = [SystemMessage(content=detailed_prompt)] + state["messages"]
        try:
            response = self.model.invoke(messages)
            text = getattr(response, "content", "").strip()
            match = re.search(r"\{.*\}", text, re.DOTALL)
            vision_data = json.loads(match.group(0)) if match else {"raw_summary": text, "item_type": "unknown"}

            # Determine category hint
            category_hint = None
            itype = (vision_data.get("item_type") or "").lower()
            if itype in ("comic", "comics"):
                category_hint = "comic"
            elif itype in ("record", "vinyl", "album", "vinyl_record"):
                category_hint = "record"
            elif itype in ("trading_card", "card", "tcg"):
                category_hint = "card"

            current_item = {
                "type": item_type,
                "title": vision_data.get("title"),
                "issue_number": vision_data.get("issue_number"),
                "publisher": vision_data.get("publisher_or_brand"),
                "condition": vision_data.get("condition_estimate"),
                "attributes": [
                    vision_data.get("variant_type"),
                    vision_data.get("legacy_number"),
                    vision_data.get("key_issue_details"),
                    vision_data.get("cover_artist_or_label"),
                ],
                "vision_summary": vision_data.get("raw_summary"),
                "category_hint": category_hint,
            }

            logger.info(
                f"[VisionNode] ✅ {current_item.get('title')} | {current_item.get('condition')} | "
                f"Category hint: {category_hint or 'general'}"
            )
        except Exception as e:
            logger.exception(f"[VisionNode] ❌ Vision structured output failed: {e}")
            current_item = {"type": item_type, "vision_summary": str(e)}

        return {
            "messages": state["messages"] + [AIMessage(content=str(current_item))],
            "session_id": state["session_id"],
            "user_id": state["user_id"],
            "current_item": current_item,
        }

    # -----------------------------------------------------------------
    # Market Node (passes category_hint)
    # -----------------------------------------------------------------
    def _market_node(self, state: PricingAgentState) -> Dict[str, Any]:
        current_item = state.get("current_item", {}) or {}
        title = current_item.get("title", "")
        issue = current_item.get("issue_number", "")
        condition = current_item.get("condition", "")
        attributes = ", ".join(a for a in current_item.get("attributes", []) if a)
        category_hint = current_item.get("category_hint")

        market_prompt = f"""
You are the market intelligence model for collectibles.
Based on the following item info, decide which pricing tools to use.
Item: "{title} {issue}" ({condition}) [{attributes}]

Available tools:
search_ebay, search_mycomicshop, search_discogs

Respond ONLY with tool call syntax, one per line:
search_ebay("Spider-Man #31 Near Mint variant cover")
search_mycomicshop("Spider-Man #31 Near Mint variant cover")
search_discogs("Chicago Transit Authority - Chicago Vinyl Record")
"""
        response = self.model.invoke([SystemMessage(content=market_prompt)])
        text = getattr(response, "content", "").strip()
        matches = re.findall(r"(\w+)\((?:\"|')?([^\"'\)]+)(?:\"|')?\)", text)

        tool_calls = []
        for i, (n, q) in enumerate(matches):
            args = {"query": q}
            if n == "search_ebay" and category_hint:
                args["category_hint"] = category_hint
            tool_calls.append({"name": n, "args": args, "id": f"toolu_{i+1}"})

        if not tool_calls:
            q = f"{title} {issue} {condition} {attributes}".strip()
            args = {"query": q}
            if category_hint:
                args["category_hint"] = category_hint
            tool_calls = [{"name": "search_ebay", "args": args, "id": "toolu_1"}]

        logger.info(f"[MarketNode] 🧩 Selected tools: {', '.join(t['name'] for t in tool_calls)}")
        response.tool_calls = tool_calls
        return {
            "messages": state["messages"] + [response],
            "session_id": state["session_id"],
            "user_id": state["user_id"],
            "current_item": current_item,
        }

    # -----------------------------------------------------------------
    # TOOL WRAPPER
    # -----------------------------------------------------------------
    async def _tool_wrapper(self, state: PricingAgentState) -> Dict[str, Any]:
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
                logger.warning(f"[ToolNode] ⚠️ Tool {tool_name} not found.")
                tool_outputs[tool_id] = {"status": "missing"}
                continue
            try:
                result = await tool_func.arun(tool_args) if hasattr(tool_func, "arun") else tool_func.run(tool_args)
                if isinstance(result, dict):
                    src = result.get("source", tool_name)
                    med = result.get("median_price")
                    avg = result.get("average_price")
                    count = result.get("sample_count")
                    logger.info(f"[{tool_name}] {src} | median={med} | avg={avg} | samples={count}")
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

    # -----------------------------------------------------------------
    # PRICING NODE
    # -----------------------------------------------------------------
    def _pricing_node(self, state: PricingAgentState) -> Dict[str, Any]:
        type_ = state.get("current_item", {}).get("type", "anything").lower()
        structure = get_schema(type_)
        tool_data = state.get("tool_results", {}) or {}
        current_item = state.get("current_item", {}) or {}

        # --- Summaries ---
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
                        base_price = val
                        break
                    if isinstance(val, str) and val.replace('.', '', 1).isdigit():
                        base_price = float(val)
                        break
            if base_price:
                break

        # --- Apply artist premium if applicable ---
        if base_price:
            attr_text = " ".join(str(a).lower() for a in current_item.get("attributes", []))
            for artist, mult in ARTIST_PREMIUMS.items():
                if artist in attr_text:
                    base_price = round(base_price * mult, 2)
                    current_item["Base_Price"] = base_price
                    logger.info(f"[PricingNode] 🎨 Artist premium applied: {artist} ×{mult}")
                    break

            current_item["Base_Price"] = base_price
            logger.info(f"[PricingNode] 💵 Base_Price: {base_price}")
        else:
            logger.info("[PricingNode] ⚠️ No numeric Base_Price detected.")

        # --- Build message chain ---
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
- Base_Price = median/lowest from tools (after adjustments).
- Price includes condition markup.
- Include reasoning in 'AI Notes'.
{context}
"""
        messages.append(SystemMessage(content=pricing_prompt))
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
            messages = [HumanMessage(content=[
                {"type": "text", "text": f"Please analyze and price this {item_type}."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}
            ])]
            state = {"messages": messages, "session_id": session_id, "user_id": user_id, "current_item": {"type": item_type}}

            result = asyncio.run(self.graph.ainvoke(state))
            parsed = result.get("pricing_result", {})
            tool_data = result.get("tool_results", {})
            logger.info(f"[PricingAgent] ✅ Full pipeline complete.")
            return {"success": True, "pricing_result": parsed, "tool_results": tool_data, "session_id": session_id}

        except Exception as e:
            logger.error(f"[PricingAgent] Error in price_item_from_image: {e}")
            return {"success": False, "error": str(e)}
