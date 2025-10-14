import base64
import os
import io
import json
import datetime
from decimal import Decimal
from openai import OpenAI
from PIL import Image
from .models import COMIC_COLUMNS, CARD_COLUMNS, RECORD_COLUMNS, ANYTHING_COLUMNS

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)


def _ts():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _price_key_for(type_):
    return "Price" if type_ == "comic" else "Final Price"


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
        Pricing:
          - Base estimates on eBay sold listings, GoCollect, or Amazon.
          - Normalize to a fair higher-midrange market price (impulse buyer level).
          - NEVER return 0 unless the item unmistakably looks custom/fan-made.
          - Rounding: >$5 → round UP to nearest dollar; $1–$5 → round UP to $0.50.
          - Minimum price = $4.00.
        Example:
        {"Title & Issue": "Action Comics #1061",
         "Bullet 1": "Superman cover appearance",
         "Bullet 2": "Modern era DC release",
         "Bullet 3": "Fresh storyline by popular writer",
         "Publisher": "DC Comics",
         "Price": "$4.00"}
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
        Pricing:
          - Base estimates on eBay sold listings, TCGPlayer, Cardmarket, or Amazon.
          - Normalize to a fair higher-midrange market price (impulse buyer level).
          - Example: a $1 Pikachu could list around $8.
          - NEVER return 0 unless the item unmistakably looks custom/fan-made.
          - Rounding: >$5 → round UP to nearest dollar; $1–$5 → round UP to $0.50.
          - Minimum price = $1.00.
        Example:
        {"Title": "Pokémon Pikachu EX",
         "Bullet 1": "Fan-favorite Pokémon",
         "Bullet 2": "Full art holo, bright foil design",
         "Price Source": "eBay/TCGPlayer/Amazon",
         "Price": "$8.00"}
        """

    elif type_ == "record":
        columns = RECORD_COLUMNS
        context = """
        Identification: Use album title, artist, record label, and year. Include genre if visible.
        If no genre, include a short **sales-oriented** point (e.g., "Classic rock essential", "Original pressing").
        Pricing:
          - Base estimates on eBay sold listings, Discogs, or Amazon.
          - Normalize to a fair higher-midrange resale value for a vintage or collectible LP.
          - Rounding: >$5 → round UP to nearest dollar; $1–$5 → round UP to $0.50.
          - Minimum price = $4.00.
        Example:
        {"Title": "Abbey Road",
         "Artist": "The Beatles",
         "Label": "Apple Records",
         "Year": "1969",
         "Genre": "Rock",
         "Price": "$12.00"}
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

    # --- Normalize schema with enforced price ---
    if type_ == "comic":
        ordered = {col: str(data.get(col, "")) for col in COMIC_COLUMNS}
        ordered["Price"] = enforce_price(ordered.get("Price", ""), "$4.00")
        if not any(ordered.values()):
            ordered["Title & Issue"] = f"Unrecognized Comic ({source_filename})"

    elif type_ == "card":
        ordered = {col: str(data.get(col, "")) for col in CARD_COLUMNS}
        ordered["Price"] = enforce_price(ordered.get("Price", ""), "$1.00")
        if not any(ordered.values()):
            ordered["Title"] = f"Unrecognized Card ({source_filename})"

    elif type_ == "record":
        ordered = {col: str(data.get(col, "")) for col in RECORD_COLUMNS}
        ordered["Price"] = enforce_price(ordered.get("Price", ""), "$4.00")
        if not any(ordered.values()):
            ordered["Title"] = f"Unrecognized Record ({source_filename})"

    else:  # anything / misc item
        ordered = {col: str(data.get(col, "")) for col in ANYTHING_COLUMNS}
        ordered["Price"] = enforce_price(ordered.get("Price", ""), "$3.00")
        if not ordered.get("AI Notes"):
            ordered["AI Notes"] = "Automatically generated pricing summary."
        if not any(ordered.values()):
            ordered["Title"] = f"Unrecognized Item ({source_filename})"

    return ordered
