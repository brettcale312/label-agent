# langgraph_agent_runner.py
"""
Persistent LangGraph agent runner with disk-backed memory.
Handles image ingestion and routes vision + pricing tasks to the LangGraph agent.
"""

import base64
import io
import os
import json
import threading
import traceback
from datetime import datetime
from PIL import Image
from langchain_core.messages import HumanMessage
from langgraph_tools.pricing_agent import PricingAgent

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)
STATE_FILE = os.path.join(LOG_DIR, "agent_state.json")

_agent = None
_agent_state = None
_state_lock = threading.Lock()


# ---------------------------------------------------------------------
# Agent Initialization & Persistence
# ---------------------------------------------------------------------
def _load_state(session_id: str):
    """Reload previous message history if it exists."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            print(f"[LangGraph] Restored {len(data.get('messages', []))} prior messages.")
            return data
        except Exception as e:
            print(f"[LangGraph] Failed to load state: {e}")

    return {
        "messages": [],
        "session_id": session_id,
        "user_id": "web_user",
        "learned_patterns": [],
        "user_preferences": {},
        "last_saved": None,
    }


def _save_state(state: dict):
    """Persist message history to disk."""
    try:
        state["last_saved"] = datetime.now().isoformat()
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        print("[LangGraph] State saved.")
    except Exception as e:
        print(f"[LangGraph] Failed to save state: {e}")


def _ensure_agent(model_name: str = "gpt-4o-mini"):
    """Thread-safe creation or reuse of the PricingAgent."""
    global _agent, _agent_state
    with _state_lock:
        if _agent is None:
            _agent = PricingAgent(model_name=model_name)
            session_id = _agent.get_or_create_session("web_user")
            _agent_state = _load_state(session_id)
            print(f"[LangGraph] Initialized persistent agent (session {session_id})")
    return _agent, _agent_state


# ---------------------------------------------------------------------
# Image Pricing Entry Point
# ---------------------------------------------------------------------
def price_image(image: Image.Image, item_type: str) -> dict:
    """
    Feed an image into the persistent agent.
    The agent will handle vision + pricing via its internal tools.
    """
    try:
        print("[LangGraph] Starting price_image...")

        agent, state = _ensure_agent()

        # --- Convert image to base64 ---
        buf = io.BytesIO()
        image.convert("RGB").save(buf, format="JPEG", quality=85, optimize=True)
        img_bytes = buf.getvalue()
        image_b64 = base64.b64encode(img_bytes).decode("utf-8")

        print(f"[LangGraph] Encoded image ({len(image_b64):,} chars)")

        # --- Compose user message ---
        user_msg = HumanMessage(
            content=[
                {"type": "text", "text": f"Please analyze and price this {item_type}."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}" }},
            ]
        )

        # --- Invoke the agent graph ---
        print("[LangGraph] Invoking graph...")
        result = agent.graph.invoke({
            **state,
            "messages": state["messages"] + [user_msg],
            "current_item": {"image_base64": image_b64, "type": item_type},
        })

        print("[LangGraph] Graph invocation complete.")

        # --- Update memory & persist ---
        with _state_lock:
            state["messages"] = result.get("messages", state["messages"])
            _save_state(state)

        pricing = result.get("pricing_result") or {}
        messages = [getattr(m, "content", "") for m in result.get("messages", [])]

        print("[LangGraph] Returning pricing result.")
        return {
            "success": True,
            "session_id": state["session_id"],
            "pricing_result": pricing,
            "messages": messages,
        }

    except Exception as e:
        traceback.print_exc()
        print(f"[LangGraph] ERROR during price_image: {e}")
        return {"success": False, "error": str(e)}
