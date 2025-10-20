import base64
import os
import io
import json
import datetime
import asyncio
from decimal import Decimal
from openai import OpenAI
from PIL import Image
from .models import COMIC_COLUMNS, CARD_COLUMNS, RECORD_COLUMNS, ANYTHING_COLUMNS
from pricing_tools.pricing_model import get_best_price
from langgraph_tools.pricing_agent import PricingAgent
from utils.logger import get_logger

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

logger = get_logger("vision")

# Global LangGraph agent instance
_langgraph_agent = None

def get_langgraph_agent():
    """Get or create the global LangGraph agent instance."""
    global _langgraph_agent
    if _langgraph_agent is None:
        _langgraph_agent = PricingAgent(model_name="gpt-4o-mini")
        logger.info("Created global LangGraph agent instance")
    return _langgraph_agent


def _ts():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def enforce_price(value: str, minimum: str):
    """Ensure a valid price string with floor enforcement."""
    if not value:
        return minimum
    clean = value.strip().replace("$", "")
    try:
        num = float(clean)
    except ValueError:
        return minimum
    if num <= 0:
        return minimum
    return f"${num:.2f}"


def log_usage(resp, source_filename: str):
    """Log token usage and estimated cost per request."""
    if not hasattr(resp, "usage"):
        return
    u = resp.usage
    input_cost = Decimal(u.prompt_tokens) / Decimal(1000) * Decimal("0.00015")
    output_cost = Decimal(u.completion_tokens) / Decimal(1000) * Decimal("0.0006")
    total_cost = input_cost + output_cost

    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_path = os.path.join(LOG_DIR, "usage.log")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(
            f"[{ts}] {source_filename} — prompt={u.prompt_tokens}, "
            f"completion={u.completion_tokens}, total={u.total_tokens}, "
            f"est cost=${total_cost:.6f}\n"
        )


def extract_issue_number(title_and_issue: str) -> str:
    """Extract issue number from title string."""
    import re
    
    # Look for patterns like "NO. 11", "#11", "Issue 11", etc.
    patterns = [
        r'NO\.?\s*(\d+)',  # "NO. 11" or "NO 11"
        r'#(\d+)',         # "#11"
        r'Issue\s*(\d+)',  # "Issue 11"
        r'(\d+)\s*JUNE',   # "11 JUNE" (from cover price area)
    ]
    
    for pattern in patterns:
        match = re.search(pattern, title_and_issue, re.IGNORECASE)
        if match:
            return match.group(1)
    
    return ""


def validate_comic_price(price: float, title: str, issue: str) -> dict:
    """Validate comic pricing and flag high-value items for review."""
    validation = {
        "is_high_value": False,
        "warning": None,
        "confidence": "high"
    }
    
    # Flag high-value items
    if price > 50:
        validation["is_high_value"] = True
        validation["warning"] = f"High value item (${price:.2f}) - verify issue number and condition"
        validation["confidence"] = "low"
    
    # Check for common misidentification patterns
    if "adventures" in title.lower() and price > 30:
        validation["warning"] = "Adventures series typically lower value - verify issue number"
        validation["confidence"] = "medium"
    
    # Flag first issues for verification
    if issue and issue.lower() in ["1", "#1", "no. 1"] and price > 20:
        validation["warning"] = "First issue detected - verify authenticity and condition"
        validation["confidence"] = "medium"
    
    # Check for suspiciously high prices on common series
    if any(series in title.lower() for series in ["adventures", "tales", "presents"]) and price > 40:
        validation["warning"] = f"High price (${price:.2f}) for common series - double-check issue number"
        validation["confidence"] = "medium"
    
    # Flag potential misreads of issue numbers
    if issue and issue.isdigit():
        issue_num = int(issue)
        if issue_num > 50 and price > 25:
            validation["warning"] = f"High issue number (#{issue}) with high price - verify authenticity"
            validation["confidence"] = "medium"
    
    return validation


async def extract_fields_with_vision(
    img: Image.Image, type_: str, source_filename: str = "uploaded_image.jpg"
):
    """
    Analyze image with OpenAI vision and return normalized fields.
    Always returns fields in correct column order.
    """
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=60.0)

    MAX_DIM = 1024
    img.thumbnail((MAX_DIM, MAX_DIM))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    b64_image = base64.b64encode(buf.getvalue()).decode("utf-8")

    # --- Dynamic prompt setup ---
    if type_ == "comic":
        columns = COMIC_COLUMNS
        context = """
        Identification: Use title, issue number, publisher, or visible cover text to identify.
        
        **CRITICAL - Issue Number Detection:**
        - Look carefully for "NO. X" format (e.g., "NO. 11 JUNE $1.00" = Issue #11)
        - Distinguish between issue number and cover price
        - Check small text near the price area
        - Cross-reference with title for validation
        
        Highlight first appearances, classic covers, popular artists, or tie-ins to shows/movies.
        Bullets: Always include 3 short **sales-oriented** points (like marketing blurbs).
        Condition: Choose from mint, near mint, very fine, fine, very good, good.
        Pricing: Base on eBay/GoCollect/Amazon; round UP.
        Minimum price = $4.00.
        
        **Price Validation:**
        - If price >$50, add note: "High value item - verify issue number and condition"
        - Include confidence level in AI Notes
        - Flag for manual review if uncertain
        """

    elif type_ == "card":
        columns = CARD_COLUMNS
        context = """
        Identification: Use title, set name (e.g., BREAKpoint), set code (e.g., XY9), card number (e.g., 032/086),
        year, rarity symbol (●, ◆, ★), and holo style.
        Return these details inside a JSON object named "Card_Metadata".
        Include the card type (Pokémon, Yu-Gi-Oh!, MTG, etc.) in the Title.
        Bullets: Include 2 short sales-oriented points (≤45 characters each).
        Condition: mint, near mint, lightly played, moderately played, heavily played, damaged.
        Pricing: Base on eBay sold listings, TCGPlayer, or Cardmarket. Round UP. Minimum $1.00.
        Example:
        {
          "Title": "Pokémon Eelektross 032/086",
          "Bullet 1": "Stage 2 Electric Pokémon",
          "Bullet 2": "Strong 140 HP with Coil attack",
          "Price": "$2.00",
          "Condition": "near mint",
          "AI Notes": "Identified as BREAKpoint rare card; pricing based on eBay.",
          "Card_Metadata": {
            "set": "BREAKpoint",
            "set_code": "XY9",
            "number": "032/086",
            "rarity": "★",
            "holo": false,
            "year": 2016
          }
        }
        """

    elif type_ == "record":
        columns = RECORD_COLUMNS
        context = """
        Identification: Include title, artist, label, year, and genre.
        Condition: sealed, mint, vg+, vg, good, fair.
        Pricing: Base on Discogs/eBay; round UP; minimum $4.00.
        """

    else:
        columns = ANYTHING_COLUMNS
        context = """
        Identification: Determine item type and short description.
        Include any markings or identifiers.
        Pricing: Estimate fair resale value for antique booth; round UP.
        Minimum price = $3.00.
        """

    prompt = f"""
    You are a collectibles cataloging assistant. Extract structured fields for a {type_} from the photo.
    Return ONLY valid JSON using these fields:
    {columns}
    {context}
    No markdown, no explanations — raw JSON only.
    """

    raw_output = ""
    data = {}

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"}}
                    ],
                }
            ],
            temperature=0.2,
        )

        raw_output = resp.choices[0].message.content.strip()
        log_usage(resp, source_filename)

        if raw_output.startswith("```"):
            raw_output = raw_output.strip("`")
            if raw_output.lower().startswith("json"):
                raw_output = raw_output[4:].strip()

        try:
            data = json.loads(raw_output) if raw_output else {}
        except json.JSONDecodeError:
            data = {}

    except Exception as e:
        data = {}
        err_path = os.path.join(LOG_DIR, f"vision_error_{_ts()}.log")
        with open(err_path, "w", encoding="utf-8") as f:
            f.write(f"=== ERROR ===\n{e}\n\nRAW OUTPUT:\n{raw_output}")

    # --- Normalize schema ---
    if type_ == "comic":
        ordered = {col: str(data.get(col, "")) for col in COMIC_COLUMNS}
        if not ordered.get("AI Notes"):
            ordered["AI Notes"] = "Automatically generated comic analysis and pricing summary."
        if not any(ordered.values()):
            ordered["Title & Issue"] = f"Unrecognized Comic ({source_filename})"
        

    elif type_ == "card":
        ordered = {col: str(data.get(col, "")) for col in CARD_COLUMNS}
        if not ordered.get("AI Notes"):
            ordered["AI Notes"] = "Automatically generated card summary."
        if not any(ordered.values()):
            ordered["Title"] = f"Unrecognized Card ({source_filename})"

        condition = ordered.get("Condition") or "near mint"

        # Extract metadata
        metadata = {}
        if isinstance(data, dict) and "Card_Metadata" in data:
            metadata = data["Card_Metadata"]
            logger.info(f"Extracted Card_Metadata: {metadata}")
        else:
            title_str = ordered.get("Title", "").lower()
            import re
            year_match = re.search(r"(19|20)\\d{2}", title_str)
            number_match = re.search(r"\\d{1,3}/\\d{1,3}", title_str)
            metadata = {
                "set": None,
                "number": number_match.group() if number_match else None,
                "rarity": "★" if "rare" in title_str else None,
                "holo": "holo" in title_str or "foil" in title_str,
                "year": int(year_match.group()) if year_match else None,
            }
            logger.info(f"Fallback metadata inferred: {metadata}")

        # --- Price lookup with LangGraph agent ---
        try:
            agent = get_langgraph_agent()
            user_id = "default_user"  # You can make this configurable later
            
            # Create or get session for this user
            session_id = agent.get_or_create_session(user_id)
            
            # Use LangGraph agent for intelligent pricing
            langgraph_result = agent.price_item(
                user_id=user_id,
                item_description=ordered.get("Title", ""),
                item_type=type_,
                condition=condition,
                session_id=session_id
            )
            
            if langgraph_result["success"]:
                # Extract pricing result from LangGraph messages
                messages = langgraph_result.get("messages", [])
                logger.info(f"LangGraph returned {len(messages)} messages")
                logger.info(f"Message types: {[type(msg) for msg in messages]}")
                pricing_result = None
                
                # Look for pricing data in tool responses
                for i, msg in enumerate(messages):
                    # Handle both message objects and strings
                    content = None
                    if hasattr(msg, 'content') and isinstance(msg.content, str):
                        content = msg.content
                    elif isinstance(msg, str):
                        content = msg
                    
                    if content:
                        try:
                            if content.startswith('{"source":'):
                                logger.info(f"Found tool response in message {i}: {content[:100]}...")
                                data = json.loads(content)
                                if data.get("source") in ["ebay_api", "cache"] and data.get("data"):
                                    pricing_result = data["data"]
                                    logger.info(f"Extracted pricing result: {pricing_result}")
                                    break
                        except Exception as e:
                            logger.warning(f"Error parsing message {i}: {e}")
                            continue
                
                if pricing_result:
                    price_result = {
                        "final_price": pricing_result.get("final_price"),
                        "base_price": pricing_result.get("base_price"),
                        "reasoning": langgraph_result.get("messages", [""])[-1] if langgraph_result.get("messages") else "LangGraph pricing analysis"
                    }
                    logger.info(f"LangGraph pricing successful: ${price_result['final_price']:.2f}")
                else:
                    logger.warning("LangGraph pricing completed but no pricing data found in messages")
                    price_result = None
            else:
                logger.warning(f"LangGraph pricing failed: {langgraph_result.get('error', 'Unknown error')}")
                # Fallback to original pricing
                price_result = get_best_price(
                    title=ordered.get("Title", ""),
                    category=type_,
                    condition=condition,
                    venue="antique_store",
                    metadata=metadata,
                )
                
        except Exception as e:
            logger.error(f"LangGraph pricing error: {e}")
            # Fallback to original pricing
            price_result = get_best_price(
                title=ordered.get("Title", ""),
                category=type_,
                condition=condition,
                venue="antique_store",
                metadata=metadata,
            )

        if price_result and price_result.get("final_price"):
            ordered["Price"] = f"${price_result['final_price']:.2f}"
            if price_result.get("reasoning"):
                ordered["AI Notes"] = price_result["reasoning"]

        if price_result and price_result.get("base_price"):
            ordered["Base_Price"] = price_result["base_price"]
            logger.info(f"Base_Price set to: {price_result['base_price']}")
            
            # Validate comic pricing and add warnings if needed
            final_price = price_result.get("final_price", 0)
            title = ordered.get("Title & Issue", "")
            issue = extract_issue_number(title)  # Properly extract issue number
            
            validation = validate_comic_price(final_price, title, issue)
            
            if validation["warning"]:
                # Add warning to AI Notes
                current_notes = ordered.get("AI Notes", "")
                warning_text = f"⚠️ {validation['warning']}"
                if current_notes:
                    ordered["AI Notes"] = f"{warning_text}\n\n{current_notes}"
                else:
                    ordered["AI Notes"] = warning_text
                
                logger.warning(f"Comic validation warning: {validation['warning']}")
                
        else:
            logger.info(f"No base_price found: {price_result}")

    elif type_ == "record":
        ordered = {col: str(data.get(col, "")) for col in RECORD_COLUMNS}
        if not ordered.get("AI Notes"):
            ordered["AI Notes"] = "Automatically generated record summary."
        if not any(ordered.values()):
            ordered["Title"] = f"Unrecognized Record ({source_filename})"

    else:
        ordered = {col: str(data.get(col, "")) for col in ANYTHING_COLUMNS}
        if not ordered.get("AI Notes"):
            ordered["AI Notes"] = "Automatically generated item summary."
        if not any(ordered.values()):
            ordered["Title"] = f"Unrecognized Item ({source_filename})"

    # --- Market pricing integration ---
    # Extract identification for pricing lookup
    title = ordered.get("Title") or ordered.get("Title & Issue")
    artist = ordered.get("Artist") if type_ == "record" else None
    
    # For records, default to "good" condition since they're in protective sleeves
    if type_ == "record":
        condition = "good"  # Default to good condition for records in protective sleeves
    else:
        condition = ordered.get("Condition") or "vg"
    
    if title and title.strip():
        try:
            logger.info(f"Getting market price for: {title} | {artist or 'N/A'} | {type_} | condition: {condition}")
            
            # Get real market pricing with LangGraph agent
            try:
                agent = get_langgraph_agent()
                user_id = "default_user"
                
                # Create or get session for this user
                session_id = agent.get_or_create_session(user_id)
                
                # Use LangGraph agent for intelligent pricing
                langgraph_result = agent.price_item(
                    user_id=user_id,
                    item_description=title,
                    item_type=type_,
                    condition=condition,
                    session_id=session_id
                )
                
                if langgraph_result["success"]:
                    # Extract pricing result from LangGraph messages
                    messages = langgraph_result.get("messages", [])
                    logger.info(f"LangGraph returned {len(messages)} messages")
                    logger.info(f"Message types: {[type(msg) for msg in messages]}")
                    pricing_result = None
                    
                    # Look for pricing data in tool responses
                    for i, msg in enumerate(messages):
                        # Handle both message objects and strings
                        content = None
                        if hasattr(msg, 'content') and isinstance(msg.content, str):
                            content = msg.content
                        elif isinstance(msg, str):
                            content = msg
                        
                        if content:
                            try:
                                if content.startswith('{"source":'):
                                    logger.info(f"Found tool response in message {i}: {content[:100]}...")
                                    data = json.loads(content)
                                    if data.get("source") in ["ebay_api", "cache"] and data.get("data"):
                                        pricing_result = data["data"]
                                        logger.info(f"Extracted pricing result: {pricing_result}")
                                        break
                            except Exception as e:
                                logger.warning(f"Error parsing message {i}: {e}")
                                continue
                    
                    if pricing_result:
                        price_result = {
                            "final_price": pricing_result.get("final_price"),
                            "base_price": pricing_result.get("base_price"),
                            "reasoning": langgraph_result.get("messages", [""])[-1] if langgraph_result.get("messages") else "LangGraph pricing analysis",
                            "sources": {"langgraph": True}
                        }
                        logger.info(f"LangGraph pricing successful: ${price_result['final_price']:.2f}")
                    else:
                        logger.warning("LangGraph pricing completed but no pricing data found in messages")
                        price_result = None
                else:
                    logger.warning(f"LangGraph pricing failed: {langgraph_result.get('error', 'Unknown error')}")
                    # Fallback to original pricing
                    price_result = get_best_price(title, artist=artist, category=type_, 
                                                condition=condition, venue="antique_store")
                    
            except Exception as e:
                logger.error(f"LangGraph pricing error: {e}")
                # Fallback to original pricing
                price_result = get_best_price(title, artist=artist, category=type_, 
                                            condition=condition, venue="antique_store")
            
            if price_result and price_result.get("final_price"):
                # Use market price
                market_price = price_result["final_price"]
                ordered["Price"] = f"${market_price:.2f}"
                
                # Log sources for debugging
                sources = price_result.get("sources", {})
                logger.info(f"Market pricing successful: ${market_price:.2f} from {list(sources.keys())}")
                
                # Add pricing reasoning to AI Notes
                if price_result.get("reasoning"):
                    existing_notes = ordered.get("AI Notes", "")
                    if existing_notes:
                        ordered["AI Notes"] = f"{existing_notes}; {price_result['reasoning']}"
                    else:
                        ordered["AI Notes"] = price_result["reasoning"]
                
                # Store base price for comics, cards, and records (don't add to AI Notes)
                if price_result.get("base_price"):
                    ordered["Base_Price"] = price_result["base_price"]
                    logger.info(f"Set Base_Price field to: {price_result['base_price']} (should be eBay median)")
                    logger.info(f"Final price was: {price_result.get('final_price')}")
                    logger.info(f"Base_Price field in ordered: {ordered.get('Base_Price')}")
                else:
                    logger.info(f"No base_price found in result: {price_result.keys()}")
                    logger.info(f"price_result contents: {price_result}")
                
                # Add pricing note if available
                if price_result.get("note"):
                    logger.info(f"Pricing note: {price_result['note']}")
                    
            else:
                # Fallback to vision estimate with appropriate minimum
                minimum_prices = {"comic": "$4.00", "record": "$4.00", "card": "$1.00", "anything": "$3.00"}
                minimum = minimum_prices.get(type_, "$3.00")
                ordered["Price"] = enforce_price(ordered.get("Price", ""), minimum)
                logger.info(f"No market data found, using vision estimate: {ordered['Price']}")
                
        except Exception as e:
            # Fallback to vision estimate on any error
            minimum_prices = {"comic": "$4.00", "record": "$4.00", "card": "$1.00", "anything": "$3.00"}
            minimum = minimum_prices.get(type_, "$3.00")
            ordered["Price"] = enforce_price(ordered.get("Price", ""), minimum)
            logger.warning(f"Market pricing failed: {e}, using vision estimate: {ordered['Price']}")
    else:
        # No title available, use vision estimate
        minimum_prices = {"comic": "$4.00", "record": "$4.00", "card": "$1.00", "anything": "$3.00"}
        minimum = minimum_prices.get(type_, "$3.00")
        ordered["Price"] = enforce_price(ordered.get("Price", ""), minimum)
        logger.warning(f"No title available, using vision estimate: {ordered['Price']}")

    # --- Append structured output to a daily log file ---
    try:
        date_str = datetime.datetime.now().strftime("%Y-%m-%d")
        out_path = os.path.join(LOG_DIR, f"vision_output_{date_str}.jsonl")  # JSON Lines file
        with open(out_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
                "source": source_filename,
                "type": type_,
                "ordered": ordered
            }) + "\n")
        logger.info(f"Appended structured output -> {out_path}")
    except Exception as e:
        logger.warning(f"Could not append vision output log: {e}")


    return ordered
