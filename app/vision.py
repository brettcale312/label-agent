import base64
import os
import io
import json
import datetime
from decimal import Decimal
from openai import OpenAI
from PIL import Image
from .models import COMIC_COLUMNS, CARD_COLUMNS

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
    if num <= 0:  # catches "0", "0.0", "0.00"
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
    # print(f"[DEBUG] Image resized to {img.size}, {len(img_bytes)/1024:.1f} KB")

    b64_image = base64.b64encode(img_bytes).decode("utf-8")

    # Prompt
    prompt = f"""
    You are a collectibles cataloging assistant. Extract details for a {type_} from the photo.
    Return ONLY valid JSON with these fields:
    For comics → {COMIC_COLUMNS}
    For cards → {CARD_COLUMNS}
    Rules:
    No markdown, no extra text, no explanations — output raw JSON only.
    Identification: Use title, set number, publisher, rarity, holo style, or visible symbols to identify.
    Bullets: Always include 2–3 short **sales-oriented** points (like marketing blurbs).
      Example: instead of "230 HP" say "High 230 HP — tough to knock out".
      For cards: each ≤45 characters.
    For comics: highlight things like first appearances, classic covers, popular artists, tie-ins to shows/movies.
    For cards: highlight fan-favorite Pokémon, strong attacks, rare holo styles, iconic characters.
    Pricing:
      - Base estimates on eBay sold listings, TCGPlayer, Cardmarket, Amazon, GoCollect.
      - Normalize to a fair higher-midrange market price (impulse buyer level).
      - Example: a $1 Pikachu could list around $8.
      - NEVER return 0 unless the item unmistakably looks custom/fan-made.
      - Rounding: >$5 → round UP to nearest dollar; $1–$5 → round UP to $0.50.
      - Min card price = $1.00. Min comic price = $4.00.
      - Format price like "$4.00".
    Example Comic:
    "Title & Issue": "Action Comics #1061",
    "Bullet 1": "Superman cover appearance",
    "Bullet 2": "Modern era DC release",
    "Bullet 3": "Fresh storyline by popular writer",
    "Publisher": "DC Comics",
    "Price": "$4.00"
    Example Card:
    "Title": "Pikachu EX",
    "Bullet 1": "Fan-favorite Pokémon",
    "Bullet 2": "Full art holo, bright foil design",
    "Price Source": "eBay/TCGPlayer/Amazon",
    "Final Price": "$8.00"
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
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"},
                        },
                    ],
                }
            ],
            temperature=0.2,
        )

        raw_output = resp.choices[0].message.content.strip()
        log_usage(resp, source_filename)

        # --- File logging disabled ---
        # raw_path = os.path.join(
        #     LOG_DIR,
        #     f"raw_{os.path.splitext(os.path.basename(source_filename))[0]}_{_ts()}.txt",
        # )
        # with open(raw_path, "w", encoding="utf-8") as f:
        #     f.write(raw_output)

        # Strip markdown fences
        if raw_output.startswith("```"):
            raw_output = raw_output.strip("`")
            if raw_output.lower().startswith("json"):
                raw_output = raw_output[4:].strip()

        # Parse JSON
        try:
            data = json.loads(raw_output) if raw_output else {}
        except json.JSONDecodeError as e:
            # print(f"[WARN] JSON parse error: {e}")
            data = {}

        # --- File logging disabled ---
        # parsed_path = os.path.join(
        #     LOG_DIR,
        #     f"parsed_{os.path.splitext(os.path.basename(source_filename))[0]}_{_ts()}.json",
        # )
        # with open(parsed_path, "w", encoding="utf-8") as f:
        #     json.dump(data, f, ensure_ascii=False, indent=2)

        pk = _price_key_for(type_)
        # print(f"[DEBUG][vision] model {pk} (pre-enforce): {repr(data.get(pk))}")

    except Exception as e:
        ts = _ts()
        safe_name = os.path.splitext(os.path.basename(source_filename))[0]
        log_filename = f"vision_error_{safe_name}_{ts}.log"
        log_path = os.path.join(LOG_DIR, log_filename)
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"=== ERROR ===\n{str(e)}\n\n")
            f.write(f"=== SOURCE FILE ===\n{source_filename}\n\n")
            f.write("=== RAW OUTPUT ===\n")
            f.write(raw_output if raw_output else "(empty)")
        # print(f"[WARN] Vision parsing failed. See {log_path}")
        data = {}

    # Normalize schema with enforced price
    if type_ == "comic":
        ordered = {col: str(data.get(col, "")) for col in COMIC_COLUMNS}
        # print(f"[DEBUG][vision] ordered Price (pre-enforce): {repr(ordered.get('Price'))}")
        ordered["Price"] = enforce_price(ordered.get("Price", ""), "$4.00")
        # print(f"[DEBUG][vision] ordered Price (post-enforce): {repr(ordered.get('Price'))}")
        if not any(ordered.values()):
            ordered["Title & Issue"] = f"Unrecognized Comic ({source_filename})"
    else:
        ordered = {col: str(data.get(col, "")) for col in CARD_COLUMNS}
        # print(f"[DEBUG][vision] ordered Final Price (pre-enforce): {repr(ordered.get('Final Price'))}")
        ordered["Final Price"] = enforce_price(ordered.get("Final Price", ""), "$1.00")
        # print(f"[DEBUG][vision] ordered Final Price (post-enforce): {repr(ordered.get('Final Price'))}")
        if not any(ordered.values()):
            ordered["Title"] = f"Unrecognized Card ({source_filename})"

    # --- File logging disabled ---
    # norm_path = os.path.join(
    #     LOG_DIR,
    #     f"vision_normalized_{os.path.splitext(os.path.basename(source_filename))[0]}_{_ts()}.json",
    # )
    # with open(norm_path, "w", encoding="utf-8") as f:
    #     json.dump(ordered, f, ensure_ascii=False, indent=2)

    return ordered
