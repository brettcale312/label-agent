"""
LangGraph Pricing Agent — unified vision + reasoning + structured output.
Handles image recognition, market search, and price reasoning inside GPT-4o.
"""

from typing import Dict, Any, List, Optional, TypedDict, Annotated
import base64
import io
import json
import operator
from PIL import Image
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_openai import ChatOpenAI

from database.connection import get_db_session
from database.operations import PricingSessionOps
from langgraph_tools.pricing_tools import pricing_tools
from schemas.pricing_schemas import get_schema
from utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------
# LangGraph State Definition
# ---------------------------------------------------------------------
class PricingAgentState(TypedDict):
    messages: Annotated[List, operator.add]
    session_id: int
    user_id: str
    current_item: Optional[Dict[str, Any]]
    pricing_result: Optional[Dict[str, Any]]


# ---------------------------------------------------------------------
# Pricing Agent Core
# ---------------------------------------------------------------------
class PricingAgent:
    """Unified pricing + vision agent."""

    def __init__(self, model_name: str = "gpt-4o-mini"):
        self.model = ChatOpenAI(model=model_name, temperature=0.2, streaming=False)
        self.tools = pricing_tools
        self.tool_node = ToolNode(self.tools)
        self.graph = self._create_graph()
        logger.info(f"[PricingAgent] Initialized with model {model_name}")

    # -----------------------------------------------------------------
    # Graph setup
    # -----------------------------------------------------------------
    def _create_graph(self) -> StateGraph:
        workflow = StateGraph(PricingAgentState)
        workflow.add_node("agent", self._agent_node)
        workflow.set_entry_point("agent")
        workflow.add_edge("agent", END)
        return workflow.compile()

    # -----------------------------------------------------------------
    # Agent core
    # -----------------------------------------------------------------
    def _agent_node(self, state: PricingAgentState) -> Dict[str, Any]:
        """Run a single reasoning step for pricing and recognition."""
        messages = [self._create_system_message(state)] + state["messages"]
        response = self.model.invoke(messages)
        return {
            "messages": [response],
            "session_id": state["session_id"],
            "user_id": state["user_id"],
        }

    # -----------------------------------------------------------------
    # System Prompt — dynamically built per schema type
    # -----------------------------------------------------------------
    def _create_system_message(self, state: PricingAgentState) -> SystemMessage:
        """Full descriptive system prompt for image + pricing reasoning."""
        type_ = state.get("current_item", {}).get("type", "anything").lower()
        structure = get_schema(type_)

        # Tailored item-type context
        if type_ == "comic":
            context = """
You are an expert in comic book identification and pricing.
- Detect title, issue number, publisher, and key visual features.
- Identify special factors: first appearances, variant covers, etc.
- Output "Title_Issue" instead of "Title".
- Always include "Publisher" and "Base_Price" even if blank.
- Include 3 concise sales bullets.
- Condition: mint, near mint, very fine, fine, good.
- Base pricing on eBay sold listings and collector market; round UP. Minimum $4.
"""
        elif type_ == "card":
            context = """
You are an expert in collectible trading cards.
- Detect title, card number, set name, rarity, holo type, and year.
- Include 2 concise sales bullets.
- Condition: mint, near mint, lightly played, moderately played, heavily played.
- Price based on eBay or TCGPlayer; round UP. Minimum $1.
"""
        elif type_ == "record":
            context = """
You are an expert in vinyl records and Discogs pricing.
- Identify title, artist, label, year, genre, and condition.
- Base pricing on Discogs/eBay sold data; round UP. Minimum $4.
"""
        else:
            context = """
You are an expert in collectible and vintage goods.
- Identify item type, material, markings, and short appealing description.
- Include 2–3 short sales bullets.
- Price for antique booth or online resale; round UP. Minimum $3.
"""

        # Structured system prompt
        full_prompt = f"""
You are a collectibles cataloging and pricing AI.
Analyze the provided image of a {type_}, reason about its market value,
and output ONLY valid JSON in the following structure:

{json.dumps(structure, indent=2)}

Rules:
- Always fill every key (use empty string if unknown).
- Do NOT include any markdown or commentary outside the JSON.
- Always include reasoning in "AI Notes".
- Round all prices UP to the nearest dollar.
{context}
"""
        return SystemMessage(content=full_prompt)

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
    # Unified Vision + Reasoning Entry
    # -----------------------------------------------------------------
    def price_item_from_image(self, user_id: str, image_bytes: bytes, item_type: str) -> Dict[str, Any]:
        """Main entry — analyzes image and returns structured pricing."""
        try:
            # --- Prepare image ---
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            image.thumbnail((1024, 1024))
            buf = io.BytesIO()
            image.save(buf, format="JPEG", quality=85)
            image_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

            session_id = self.get_or_create_session(user_id)

            # --- Construct message list ---
            messages = [
                HumanMessage(
                    content=[
                        {"type": "text", "text": f"Please analyze and price this {item_type}."},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                    ]
                )
            ]

            state = {
                "messages": messages,
                "session_id": session_id,
                "user_id": user_id,
                "current_item": {"type": item_type},
            }

            # --- Invoke graph ---
            result = self.graph.invoke(state)
            final_message = result.get("messages", [])[-1]
            content = getattr(final_message, "content", None)

            # --- Parse structured JSON ---
            parsed = {}
            if isinstance(content, str):
                try:
                    parsed = json.loads(content)
                except Exception:
                    parsed = {"Title_Issue": "Unrecognized item", "AI Notes": content}
            elif isinstance(content, list):
                # Handle OpenAI multi-part outputs
                for part in content:
                    if isinstance(part, str) and part.strip().startswith("{"):
                        try:
                            parsed = json.loads(part)
                            break
                        except Exception:
                            continue

            logger.info(f"[PricingAgent] Parsed JSON result: {parsed}")
            return {"success": True, "pricing_result": parsed, "session_id": session_id}

        except Exception as e:
            logger.error(f"[PricingAgent] Error in price_item_from_image: {e}")
            return {"success": False, "error": str(e)}
