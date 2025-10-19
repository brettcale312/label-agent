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
from utils.logger import get_logger

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# Initialize logger for vision module
logger = get_logger("vision")


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


async def extract_fields_with_vision(
    img: Image.Image, type_: str, source_filename: str = "uploaded_image.jpg"
):
    """
    Analyze image with OpenAI vision and return normalized fields.
    Always returns fields in correct column order.
    """
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=60.0)

    # Resize image to reduce payload size
    MAX_DIM = 1024
    img.thumbnail((MAX_DIM, MAX_DIM))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    img_bytes = buf.getvalue()
    b64_image = base64.b64encode(img_bytes).decode("utf-8")

    # --- Dynamically build prompt per item type ---
    if type_ == "comic":
        columns = COMIC_COLUMNS
        context = """
        Identification: Use title, issue number, publisher, or visible cover text to identify.
        Highlight first appearances, classic covers, popular artists, or tie-ins to shows/movies.
        Bullets: Always include 3 short **sales-oriented** points (like marketing blurbs).
          Example: instead of "Variant cover" say "Limited variant cover by fan-favorite artist".
        Condition: Assess the comic's physical condition based on visible cues:
          - "mint": Near perfect, no visible wear or damage
          - "near mint": Excellent condition, minimal handling wear
          - "very fine": Very good condition, slight wear
          - "fine": Good condition, some wear but well-preserved
          - "very good": Noticeable wear but still collectible
          - "good": Fair condition, significant wear but intact
        Pricing:
          - Base estimates on eBay sold listings, GoCollect, or Amazon.
          - Normalize to a fair higher-midrange market price (impulse buyer level).
          - NEVER return 0 unless the item unmistakably looks custom/fan-made.
          - Rounding: >$5 → round UP to nearest dollar; $1–$5 → round UP to $0.50.
          - Minimum price = $4.00.
        AI Notes: Include a short paragraph (2–3 sentences) explaining:
          - What you identified about the comic,
          - How you derived the suggested price,
          - Notable condition observations or special features.
        Example:
        {"Title & Issue": "Action Comics #1061",
         "Bullet 1": "Superman cover appearance",
         "Bullet 2": "Modern era DC release",
         "Bullet 3": "Fresh storyline by popular writer",
         "Publisher": "DC Comics",
         "Price": "$4.00",
         "Condition": "fine",
         "AI Notes": "Identified as modern Superman comic with clean cover; pricing based on similar modern era DC comics; minimal edge wear observed."}
        """

    elif type_ == "card":
        columns = CARD_COLUMNS
        context = """
        Identification: Use title, set number, rarity, holo style, or visible symbols to identify.
        Include the type of card in the Title. Pokémon, Yu-Gi-Oh!, Star Wars, MTG, Spider-Man, etc.
        Bullets: Always include 2 short **sales-oriented** points (like marketing blurbs).
          Example: instead of "230 HP" say "High 230 HP — tough to knock out".
          Each bullet ≤45 characters.
        Highlight fan-favorite Pokémon, strong attacks, rare holo styles, or iconic characters.
        Condition: Assess the card's physical condition based on visible cues:
          - "mint": Near perfect, no visible wear or damage
          - "near mint": Excellent condition, minimal handling wear
          - "lightly played": Very good condition, slight wear
          - "moderately played": Good condition, some wear but well-preserved
          - "heavily played": Noticeable wear but still playable
          - "damaged": Significant wear, creases, or damage
        Pricing:
          - Base estimates on eBay sold listings, TCGPlayer, Cardmarket, or Amazon.
          - Normalize to a fair higher-midrange market price (impulse buyer level).
          - Example: a $1 Pikachu could list around $8.
          - NEVER return 0 unless the item unmistakably looks custom/fan-made.
          - Rounding: >$5 → round UP to nearest dollar; $1–$5 → round UP to $0.50.
          - Minimum price = $1.00.
        AI Notes: Include a short paragraph (2–3 sentences) explaining:
          - What you identified about the card,
          - How you derived the suggested price,
          - Notable condition observations or special features.
        Example:
        {"Title": "Pokémon Pikachu EX",
         "Bullet 1": "Fan-favorite Pokémon",
         "Bullet 2": "Full art holo, bright foil design",
         "Price Source": "eBay/TCGPlayer/Amazon",
         "Price": "$8.00",
         "Condition": "near mint",
         "AI Notes": "Identified as Pokémon EX card with holo foil pattern; pricing based on popular Pikachu character and EX rarity; card shows minimal handling wear."}
        """

    elif type_ == "record":
        columns = RECORD_COLUMNS
        context = """
        Identification: Use album title, artist, record label, and year. Include genre if visible.
        If no genre, include a short **sales-oriented** point (e.g., "Classic rock essential", "Original pressing").
        Condition: Assess the record's physical condition based on visible cues:
          - "sealed": Still in original shrink wrap from manufacturer (NOT just a protective sleeve)
          - "mint": Near perfect, no visible wear, may be in protective sleeve
          - "vg+": Very good plus, minimal wear, may be in protective sleeve
          - "vg": Very good, some wear but plays well, may be in protective sleeve
          - "good": Good condition, noticeable wear but functional
          - "fair": Fair condition, significant wear but playable
        Pricing:
          - Base estimates on eBay sold listings, Discogs, or Amazon.
          - Normalize to a fair higher-midrange resale value for a vintage or collectible LP.
          - Rounding: >$5 → round UP to nearest dollar; $1–$5 → round UP to $0.50.
          - Minimum price = $4.00.
        AI Notes: Include a short paragraph (2–3 sentences) explaining:
          - What you identified about the record,
          - How you derived the suggested price,
          - Notable condition observations or special features.
        Example:
        {"Title": "Abbey Road",
         "Artist": "The Beatles",
         "Label": "Apple Records",
         "Year": "1969",
         "Genre": "Rock",
         "Price": "$12.00",
         "Condition": "vg",
         "AI Notes": "Identified as classic Beatles album with distinctive cover art; pricing based on vintage rock LP market values; some wear on cover but vinyl appears playable. Record appears to be in protective sleeve, not original shrink wrap."}
        """

    else:  # anything / misc item
        columns = ANYTHING_COLUMNS
        context = """
        Identification: Determine what the item is (type of object), its likely category (e.g., furniture, décor, tool, collectible),
        and provide a concise description. Include any notable markings or details that affect value.
        Bullets are optional; focus on descriptive accuracy.

        Additionally, include an "AI Notes" field with a short paragraph (2–3 sentences) explaining:
          - What you identified about the item,
          - How you derived the suggested price,
          - Comparable listings or observed condition cues.

        Pricing:
          - Estimate a fair resale price in an antique booth or vintage shop context.
          - Use similar eBay sold listings or Etsy comparables as reference.
          - Normalize to what a typical buyer would pay impulsively for display pieces.
          - Rounding: >$5 → round UP to nearest dollar; $1–$5 → round UP to $0.50.
          - Minimum price = $3.00.
        Example:
        {"Title": "Vintage Glass Pitcher",
         "Category": "Kitchenware",
         "Description": "Embossed glass, mid-century style",
         "Price": "$9.00",
         "AI Notes": "Identified as mid-century pressed glass; similar examples sold $8–12 on eBay, good booth impulse item."}
        """

    # --- Build prompt ---
    prompt = f"""
    You are a collectibles cataloging assistant. Extract details for a {type_} from the photo.
    Return ONLY valid JSON with these fields:
    {columns}

    Rules:
    No markdown, no extra text, no explanations — output raw JSON only.
    {context}
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
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"}},
                    ],
                }
            ],
            temperature=0.2,
        )

        raw_output = resp.choices[0].message.content.strip()
        log_usage(resp, source_filename)

        # Strip markdown fences
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

    # --- Normalize schema with market pricing integration ---
    if type_ == "comic":
        ordered = {col: str(data.get(col, "")) for col in COMIC_COLUMNS}
        if not ordered.get("AI Notes"):
            ordered["AI Notes"] = "Automatically generated comic analysis and pricing summary."
        if not any(ordered.values()):
            ordered["Title & Issue"] = f"Unrecognized Comic ({source_filename})"

    elif type_ == "card":
        ordered = {col: str(data.get(col, "")) for col in CARD_COLUMNS}
        if not ordered.get("AI Notes"):
            ordered["AI Notes"] = "Automatically generated card analysis and pricing summary."
        if not any(ordered.values()):
            ordered["Title"] = f"Unrecognized Card ({source_filename})"

    elif type_ == "record":
        ordered = {col: str(data.get(col, "")) for col in RECORD_COLUMNS}
        if not ordered.get("AI Notes"):
            ordered["AI Notes"] = "Automatically generated record analysis and pricing summary."
        if not any(ordered.values()):
            ordered["Title"] = f"Unrecognized Record ({source_filename})"

    else:  # anything / misc item
        ordered = {col: str(data.get(col, "")) for col in ANYTHING_COLUMNS}
        if not ordered.get("AI Notes"):
            ordered["AI Notes"] = "Automatically generated pricing summary."
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
            
            # Get real market pricing (async-safe execution)
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
                
                # Store base price for comics (don't add to AI Notes)
                if type_ == "comic" and price_result.get("base_price"):
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

    return ordered
