"""
vision.py
---------
Analyzes card image(s) using AI vision to extract metadata, generate sales
bullets, and provide a knowledge-based price estimate.

Supports Anthropic (default) and OpenAI — swap via AI_PROVIDER in .env.
"""

import base64
import json
import re
import logging
from typing import Optional

from .config import AI_PROVIDER, ANTHROPIC_MODEL, OPENAI_MODEL, GEMINI_MODEL, GEMINI_API_KEY
from .models import CardVisionResult

logger = logging.getLogger("vision")


# ─────────────────────────────────────────────────────────────────────────────
# Prompt
# ─────────────────────────────────────────────────────────────────────────────

VISION_PROMPT = """You are an expert collectible card appraiser with deep knowledge of:
- Pokemon TCG (all sets, holos, alt arts, promos, full arts, rainbow rares, etc.)
- Sports cards (Topps, Panini, Bowman, Prizm, baseball/basketball/football/hockey)
- Magic: The Gathering
- Yu-Gi-Oh!
- Other trading card games

Analyze the provided card image(s) and return ONLY a JSON object with this exact structure:

{
  "title": "Card name + variant, abbreviated if needed so the full display label (title + set_name + card_number) stays under 60 characters. The display label is built as: '{title} ({set_name} #{card_number})'. Keep set_name and card_number exact — shorten the title portion if the combined result would exceed 60 chars. Examples: 'Charizard VMAX' (not 'Charizard VMAX Rainbow Rare Secret'), 'Mike Trout RC' (not 'Mike Trout 2011 Bowman Chrome Rookie Auto')",
  "set_name": "Set or product name — always exact, never abbreviated (e.g., 'Champions Path', '2023 Topps Series 1')",
  "card_number": "Card number as printed (e.g., '074/073' — leave blank if not visible)",
  "rarity": "Rarity tier (e.g., 'Rainbow Rare', 'Holo Rare', 'Common', 'Prizm', 'Silver Refractor')",
  "condition": "One of: Mint/NM, Good/VG, Fair/GD, Poor — based on visible wear, centering, surface scratches",
  "publisher_brand": "Brand (e.g., 'Pokemon', 'Topps', 'Panini', 'Upper Deck', 'Wizards of the Coast')",
  "year": "Year if visible on card, otherwise blank",
  "bullet_1": "Selling point for retail tag — MAX 50 characters, punchy marketing copy (e.g., 'Fan-favorite holo with iconic artwork')",
  "bullet_2": "Rarity or collectibility point — MAX 50 characters (e.g., 'Secret Rare — 1 in 72 packs')",
  "bullet_3": "Condition, set, or investment point — MAX 50 characters (e.g., 'Near Mint from sought-after set')",
  "ai_price_low": <your low-end estimate of raw secondary market value in USD as a number, e.g., 4.50>,
  "ai_price_high": <your high-end estimate of raw secondary market value in USD as a number, e.g., 8.00>,
  "ai_price_confidence": "high if you know this card's market value well, medium if approximate, low if uncertain",
  "search_query": "Exact search string to find this card on PriceCharting or eBay (e.g., 'Charizard VMAX 074/073 Champions Path Pokemon')",
  "is_fan_art": true or false — set true if this is a custom, fan-made, unofficial, or AI-generated card. Signs include: anime/game crossover characters on Pokemon cards (Naruto, Dragon Ball, etc.), obvious non-official artwork style, labeled as VCOS or similar fan series, non-standard card layout, or any card that is clearly not an official TCG product
}

LABEL SIZE CONSTRAINTS — this prints on a 2×2 inch thermal label, space is very tight:

For title (the display label = "{title} ({set_name} #{card_number})"):
- The combined display label must be 60 characters or fewer
- Keep set_name and card_number always exact — abbreviate the title portion if needed
- Drop redundant words: "Holo Rare" can become just the key variant ("VMAX", "ex", "GX", "V")
- For sports cards: use abbreviations like "RC" (rookie), player last name + year if needed

For bullet_1, bullet_2, bullet_3:
- Each must be 50 characters or fewer — count carefully
- Short punchy phrases, not full sentences
- Specific beats generic: "First-edition holo" beats "Rare collectible card"

For ai_price_low / ai_price_high:
- This card will be sold at an antique mall booth targeting casual impulse buyers — people
  browsing without doing research. Price like a card shop would, not like the lowest eBay
  sold listing. Think "what would someone happily pay seeing this on a shelf?"
- Base on your training knowledge of this specific card's demand, print run, set, and rarity
- Even if uncertain, give your best estimate — the owner will review and can adjust
- Minimums: nothing under $1.00. Common bulk cards worth pennies online → $1.00–$2.00 at a booth
- Set ai_price_confidence to "high" only if you know this specific card's market value well

For search_query:
- Make it specific enough to find THIS exact card (include number, set, game if known)
- Avoid vague terms — "Pokemon card" alone won't find a price
- search_query is NOT length-constrained — be as specific as needed

Return ONLY the JSON object. No explanation, no markdown fences."""


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _detect_media_type(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _parse_json(text: str) -> dict:
    """Tolerant JSON extractor — handles markdown fences and extra text."""
    text = text.strip()
    # Strip ```json ... ``` fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]+\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Could not parse JSON from AI response: {text[:300]}")


def _build_result(data: dict) -> CardVisionResult:
    """Coerce types and build a CardVisionResult from raw dict."""
    for field in ("ai_price_low", "ai_price_high"):
        val = data.get(field)
        if val is not None:
            try:
                data[field] = float(val)
            except (ValueError, TypeError):
                data[field] = None
    # Only pass fields that exist in the model
    valid_keys = CardVisionResult.model_fields.keys()
    return CardVisionResult(**{k: v for k, v in data.items() if k in valid_keys})


# ─────────────────────────────────────────────────────────────────────────────
# Provider implementations
# ─────────────────────────────────────────────────────────────────────────────

def _build_prompt(batch_notes: str) -> str:
    """Prepend batch context to the vision prompt if provided."""
    if not batch_notes or not batch_notes.strip():
        return VISION_PROMPT
    return (
        f"BATCH CONTEXT — applies to every card in this session:\n"
        f"{batch_notes.strip()}\n\n"
        f"Use this context to help identify cards (e.g. if the batch says "
        f"'Pokemon fan art', treat all cards accordingly).\n\n"
        + VISION_PROMPT
    )


async def _analyze_anthropic(image_bytes_list: list[bytes], batch_notes: str = "") -> CardVisionResult:
    import anthropic
    client = anthropic.AsyncAnthropic()

    content = []
    for img_bytes in image_bytes_list:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": _detect_media_type(img_bytes),
                "data": base64.standard_b64encode(img_bytes).decode(),
            },
        })
    content.append({"type": "text", "text": _build_prompt(batch_notes)})

    response = await client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": content}],
    )

    raw = response.content[0].text
    logger.info(f"[vision] Anthropic raw response length: {len(raw)}")
    return _build_result(_parse_json(raw))


async def _analyze_openai(image_bytes_list: list[bytes], batch_notes: str = "") -> CardVisionResult:
    from openai import AsyncOpenAI
    client = AsyncOpenAI()

    content = []
    for img_bytes in image_bytes_list:
        mt = _detect_media_type(img_bytes)
        b64 = base64.standard_b64encode(img_bytes).decode()
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mt};base64,{b64}"},
        })
    content.append({"type": "text", "text": _build_prompt(batch_notes)})

    response = await client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": content}],
        max_tokens=1024,
    )

    raw = response.choices[0].message.content
    logger.info(f"[vision] OpenAI raw response length: {len(raw)}")
    return _build_result(_parse_json(raw))


async def _analyze_gemini(image_bytes_list: list[bytes], batch_notes: str = "") -> CardVisionResult:
    import google.generativeai as genai
    import PIL.Image
    import io

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(GEMINI_MODEL)

    # Convert raw bytes to PIL Images (what Gemini's SDK expects for inline images)
    images = [PIL.Image.open(io.BytesIO(b)) for b in image_bytes_list]

    prompt = _build_prompt(batch_notes)
    # Gemini content list: [prompt_text, image1, image2, ...]
    response = await model.generate_content_async([prompt] + images)

    raw = response.text
    logger.info(f"[vision] Gemini raw response length: {len(raw)}")
    return _build_result(_parse_json(raw))


# ─────────────────────────────────────────────────────────────────────────────
# Public interface
# ─────────────────────────────────────────────────────────────────────────────

async def analyze_card(image_bytes_list: list[bytes], batch_notes: str = "") -> CardVisionResult:
    """
    Analyze one or more card images and return structured metadata + price estimate.
    batch_notes — optional context string from the batch (e.g. "Pokemon fan art cards").
    Provider is selected by AI_PROVIDER in config.py / .env.
    """
    logger.info(f"[vision] Analyzing {len(image_bytes_list)} image(s) via {AI_PROVIDER}" +
                (f" | batch_notes={batch_notes!r}" if batch_notes else ""))
    if AI_PROVIDER == "openai":
        return await _analyze_openai(image_bytes_list, batch_notes=batch_notes)
    if AI_PROVIDER == "gemini":
        return await _analyze_gemini(image_bytes_list, batch_notes=batch_notes)
    return await _analyze_anthropic(image_bytes_list, batch_notes=batch_notes)
