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
        Highlight first appearances, classic covers, popular artists, or tie-ins to shows/movies.
        Bullets: Always include 3 short **sales-oriented** points (like marketing blurbs).
        Condition: Choose from mint, near mint, very fine, fine, very good, good.
        Pricing: Base on eBay/GoCollect/Amazon; round UP.
        Minimum price = $4.00.
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
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"}}.
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
            ordered["AI Notes"] = "Automatically generated comic summary."
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

        # --- Price lookup ---
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
        logger.info(f"Appended structured output → {out_path}")
    except Exception as e:
        logger.warning(f"Could not append vision output log: {e}")


    return ordered
