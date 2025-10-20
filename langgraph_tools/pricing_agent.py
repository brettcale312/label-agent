"""
LangGraph pricing agent with session management and database integration.
"""

from typing import Dict, Any, List, Optional, TypedDict, Annotated
from datetime import datetime
import operator

from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_openai import ChatOpenAI

from database.connection import get_db_session
from database.operations import PricingSessionOps
from langgraph_tools.pricing_tools import pricing_tools
from utils.logger import get_logger

logger = get_logger(__name__)


class PricingAgentState(TypedDict):
    """State for the pricing agent."""
    messages: Annotated[List, operator.add]
    session_id: int
    user_id: str
    current_item: Optional[Dict[str, Any]]
    pricing_result: Optional[Dict[str, Any]]
    learned_patterns: List[Dict[str, Any]]
    user_preferences: Dict[str, Any]


class PricingAgent:
    """LangGraph pricing agent with persistent session management."""
    
    def __init__(self, model_name: str = "gpt-4o-mini"):
        self.model = ChatOpenAI(model=model_name, temperature=0.1)
        self.tools = pricing_tools
        self.tool_node = ToolNode(self.tools)
        
        # Create the graph
        self.graph = self._create_graph()
        
    def _create_graph(self) -> StateGraph:
        """Create the LangGraph workflow."""
        
        # Create the state graph
        workflow = StateGraph(PricingAgentState)
        
        # Add nodes
        workflow.add_node("agent", self._agent_node)
        workflow.add_node("tools", self.tool_node)
        workflow.add_node("save_results", self._save_results_node)
        
        # Set entry point
        workflow.set_entry_point("agent")
        
        # Add edges
        workflow.add_conditional_edges(
            "agent",
            self._should_use_tools,
            {
                "tools": "tools",
                "save": "save_results",
                "end": END
            }
        )
        
        workflow.add_edge("tools", "agent")
        workflow.add_edge("save_results", END)
        
        return workflow.compile()
    
    def _agent_node(self, state: PricingAgentState) -> Dict[str, Any]:
        """Main agent node that processes pricing requests."""
        
        # Get user preferences
        if not state.get("user_preferences"):
            prefs_result = self.tools[5].invoke({"user_id": state["user_id"]})  # get_user_preferences
            state["user_preferences"] = prefs_result
        
        # Get learned patterns for context
        if not state.get("learned_patterns"):
            patterns_result = self.tools[3].invoke({"pattern_type": "series_pricing"})  # get_learned_patterns
            state["learned_patterns"] = patterns_result
        
        # Create system message with context
        system_message = self._create_system_message(state)
        
        # Add system message to state
        messages = [system_message] + state["messages"]
        
        # Bind tools to model for this conversation
        model_with_tools = self.model.bind_tools(self.tools)
        
        # Get response from model
        response = model_with_tools.invoke(messages)
        
        return {
            "messages": [response],
            "session_id": state["session_id"],
            "user_id": state["user_id"],
            "current_item": state.get("current_item"),
            "pricing_result": state.get("pricing_result"),
            "learned_patterns": state.get("learned_patterns", []),
            "user_preferences": state.get("user_preferences", {})
        }
    
    def _create_system_message(self, state: PricingAgentState) -> SystemMessage:
        """Create system message with context and instructions."""
        
        prefs = state.get("user_preferences", {})
        patterns = state.get("learned_patterns", [])
        
        system_prompt = f"""You are an expert collectibles pricing assistant with access to real-time market data and learning capabilities.

## Your Capabilities:
- Search eBay, Discogs, and web for pricing data
- Access learned patterns from previous sessions
- Save new patterns as you learn
- Remember user preferences and session context

## Current Context:
- User ID: {state["user_id"]}
- Session ID: {state["session_id"]}
- User Preferences: {prefs}

## Learned Patterns:
{self._format_patterns(patterns)}

## Pricing Guidelines:
1. **Data Sources**: Use eBay for recent sales, Discogs for records, web search for additional context
2. **Condition Impact**: Apply appropriate multipliers based on condition
3. **Venue Context**: User prefers {prefs.get('default_venue', 'antique_store')} pricing
4. **Learning**: Save patterns when you notice trends or make corrections
5. **Reasoning**: Always explain your pricing logic clearly

## Available Tools:
- search_ebay_prices: Get eBay pricing data
- search_discogs_prices: Get Discogs pricing data (records only)
- search_web_prices: Search web for additional pricing context
- get_learned_patterns: Retrieve patterns from previous sessions
- save_learned_pattern: Save new patterns you discover
- get_user_preferences: Get user's pricing preferences
- save_priced_item: Save the final pricing result
- get_session_history: View items processed in this session

## Process:
1. Analyze the item description and identify key details
2. Search relevant pricing sources (eBay, Discogs, web)
3. Apply condition multipliers and venue adjustments
4. Consider learned patterns and user preferences
5. Provide clear reasoning for your pricing decision
6. Save the result and any new patterns learned

Always be thorough in your analysis and transparent in your reasoning."""
        
        return SystemMessage(content=system_prompt)
    
    def _format_patterns(self, patterns: List[Dict[str, Any]]) -> str:
        """Format learned patterns for display."""
        if not patterns:
            return "No learned patterns available yet."
        
        formatted = []
        for pattern in patterns[:5]:  # Show top 5 patterns
            formatted.append(
                f"- {pattern['pattern_key']}: {pattern['pattern_data']} "
                f"(confidence: {pattern['confidence_score']:.2f}, samples: {pattern['sample_size']})"
            )
        
        return "\n".join(formatted)
    
    def _should_use_tools(self, state: PricingAgentState) -> str:
        """Determine if tools should be used or if we should save results."""
        
        last_message = state["messages"][-1]
        
        # Check if the last message contains tool calls
        if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
            return "tools"
        
        # Check if we have a pricing result to save
        if state.get("pricing_result"):
            return "save"
        
        # Check if the message indicates completion
        content = last_message.content.lower()
        if any(phrase in content for phrase in ["final price", "pricing complete", "save result"]):
            return "save"
        
        return "end"
    
    def _save_results_node(self, state: PricingAgentState) -> Dict[str, Any]:
        """Save pricing results to database."""
        
        if not state.get("pricing_result"):
            return {"messages": [AIMessage(content="No pricing result to save.")]}
        
        try:
            # Save the priced item
            save_result = self.tools[6].invoke({  # save_priced_item
                "session_id": state["session_id"],
                "item_data": state["pricing_result"]
            })
            
            if save_result["success"]:
                return {
                    "messages": [AIMessage(content=f"✅ Pricing result saved successfully. Item ID: {save_result['item_id']}")]
                }
            else:
                return {
                    "messages": [AIMessage(content=f"❌ Error saving pricing result: {save_result.get('error', 'Unknown error')}")]
                }
                
        except Exception as e:
            logger.error(f"Error in save_results_node: {e}")
            return {
                "messages": [AIMessage(content=f"❌ Error saving results: {str(e)}")]
            }
    
    def create_session(self, user_id: str, session_name: Optional[str] = None) -> int:
        """Create a new pricing session."""
        try:
            db = get_db_session()
            try:
                session = PricingSessionOps.create_session(db, user_id, session_name)
                logger.info(f"Created new pricing session: {session.id} for user: {user_id}")
                return session.id
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error creating session: {e}")
            raise
    
    def get_or_create_session(self, user_id: str) -> int:
        """Get existing active session or create a new one."""
        try:
            db = get_db_session()
            try:
                # Try to get existing active session
                session = PricingSessionOps.get_active_session(db, user_id)
                if session:
                    logger.info(f"Using existing session: {session.id} for user: {user_id}")
                    return session.id
                
                # Create new session if none exists
                return self.create_session(user_id)
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error getting/creating session: {e}")
            raise
    
    def price_item(self, user_id: str, item_description: str, item_type: str, 
                  condition: Optional[str] = None, session_id: Optional[int] = None) -> Dict[str, Any]:
        """Price an item using the LangGraph agent."""
        
        try:
            # Get or create session
            if not session_id:
                session_id = self.get_or_create_session(user_id)
            
            # Create initial state
            initial_state = {
                "messages": [HumanMessage(content=f"Price this {item_type}: {item_description}. Condition: {condition or 'unknown'}")],
                "session_id": session_id,
                "user_id": user_id,
                "current_item": {
                    "description": item_description,
                    "type": item_type,
                    "condition": condition
                }
            }
            
            # Run the graph
            result = self.graph.invoke(initial_state)
            
            # Extract the final pricing result
            final_messages = result.get("messages", [])
            pricing_result = result.get("pricing_result")
            
            return {
                "success": True,
                "session_id": session_id,
                "pricing_result": pricing_result,
                "messages": [msg.content for msg in final_messages if hasattr(msg, 'content')],
                "conversation_history": result.get("messages", [])
            }
            
        except Exception as e:
            logger.error(f"Error pricing item: {e}")
            return {
                "success": False,
                "error": str(e),
                "session_id": session_id
            }
