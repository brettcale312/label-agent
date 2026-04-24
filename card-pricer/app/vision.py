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

from .config import (
    AI_PROVIDER, ANTHROPIC_MODEL, OPENAI_MODEL, GEMINI_MODEL, GEMINI_API_KEY,
    ENABLE_GENERALIST_MODE,
)
from .models import CardVisionResult
from .prompts import build_prompt, CARD_PROMPT

logger = logging.getLogger("vision")


# ─────────────────────────────────────────────────────────────────────────────
# Prompt
# ─────────────────────────────────────────────────────────────────────────────
# The full card prompt now lives in app/prompts/card.py — preserved verbatim.
# VISION_PROMPT stays here as a backwards-compatible alias.

VISION_PROMPT = CARD_PROMPT


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

def _build_prompt(batch_notes: str, category: str = "card") -> str:
    """Return the full prompt for a category, with optional batch context.
    When ENABLE_GENERALIST_MODE is off, forces card prompt regardless of category."""
    effective_category = category if ENABLE_GENERALIST_MODE else "card"
    return build_prompt(effective_category, batch_notes)


async def _analyze_anthropic(image_bytes_list: list[bytes], batch_notes: str = "", category: str = "card") -> CardVisionResult:
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
    content.append({"type": "text", "text": _build_prompt(batch_notes, category)})

    response = await client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": content}],
    )

    raw = response.content[0].text
    logger.info(f"[vision] Anthropic raw response length: {len(raw)}")
    return _build_result(_parse_json(raw))


async def _analyze_openai(image_bytes_list: list[bytes], batch_notes: str = "", category: str = "card") -> CardVisionResult:
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
    content.append({"type": "text", "text": _build_prompt(batch_notes, category)})

    response = await client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": content}],
        max_tokens=1024,
    )

    raw = response.choices[0].message.content
    logger.info(f"[vision] OpenAI raw response length: {len(raw)}")
    return _build_result(_parse_json(raw))


async def _analyze_gemini(image_bytes_list: list[bytes], batch_notes: str = "", category: str = "card") -> CardVisionResult:
    import google.generativeai as genai
    import PIL.Image
    import io

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(GEMINI_MODEL)

    # Convert raw bytes to PIL Images (what Gemini's SDK expects for inline images)
    images = [PIL.Image.open(io.BytesIO(b)) for b in image_bytes_list]

    prompt = _build_prompt(batch_notes, category)
    # Gemini content list: [prompt_text, image1, image2, ...]
    response = await model.generate_content_async([prompt] + images)

    raw = response.text
    logger.info(f"[vision] Gemini raw response length: {len(raw)}")
    return _build_result(_parse_json(raw))


# ─────────────────────────────────────────────────────────────────────────────
# Public interface
# ─────────────────────────────────────────────────────────────────────────────

_UPC_PROMPT = (
    "Read the UPC or EAN barcode number from this image. "
    "The number is usually printed in digits below the bars — use those printed digits "
    "as your primary source, and cross-check against the barcode bars if both are visible. "
    "Return ONLY the digits with no spaces or dashes. "
    "If you cannot clearly read a barcode or digits, return the single word: null"
)


async def extract_upc(image_bytes: bytes) -> Optional[str]:
    """Send a barcode image to the active AI provider and return the UPC digits, or None."""
    mt = _detect_media_type(image_bytes)
    b64 = base64.standard_b64encode(image_bytes).decode()

    try:
        if AI_PROVIDER == "openai":
            from openai import AsyncOpenAI
            client = AsyncOpenAI()
            resp = await client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[{"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mt};base64,{b64}"}},
                    {"type": "text", "text": _UPC_PROMPT},
                ]}],
                max_tokens=32,
            )
            raw = resp.choices[0].message.content.strip()
        elif AI_PROVIDER == "gemini":
            import google.generativeai as genai
            import PIL.Image, io
            genai.configure(api_key=GEMINI_API_KEY)
            model = genai.GenerativeModel(GEMINI_MODEL)
            img = PIL.Image.open(io.BytesIO(image_bytes))
            resp = await model.generate_content_async([_UPC_PROMPT, img])
            raw = resp.text.strip()
        else:
            import anthropic
            client = anthropic.AsyncAnthropic()
            resp = await client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=32,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": mt, "data": b64}},
                    {"type": "text", "text": _UPC_PROMPT},
                ]}],
            )
            raw = resp.content[0].text.strip()

        digits = re.sub(r"[^0-9]", "", raw)
        if len(digits) >= 8:
            logger.info(f"[vision] UPC extracted: {digits}")
            return digits
        logger.info(f"[vision] UPC extraction returned no valid digits: {raw!r}")
        return None
    except Exception as e:
        logger.warning(f"[vision] UPC extraction failed: {e}")
        return None


async def analyze_card(image_bytes_list: list[bytes], batch_notes: str = "", category: str = "card") -> CardVisionResult:
    """
    Analyze one or more images and return structured metadata + price estimate.
    batch_notes — optional context string from the batch (e.g. "Pokemon fan art cards").
    category — "card" (default) or a non-card category when ENABLE_GENERALIST_MODE=true.
    Provider is selected by AI_PROVIDER in config.py / .env.
    """
    logger.info(f"[vision] Analyzing {len(image_bytes_list)} image(s) via {AI_PROVIDER}"
                f" | category={category!r}" +
                (f" | batch_notes={batch_notes!r}" if batch_notes else ""))
    if AI_PROVIDER == "openai":
        return await _analyze_openai(image_bytes_list, batch_notes=batch_notes, category=category)
    if AI_PROVIDER == "gemini":
        return await _analyze_gemini(image_bytes_list, batch_notes=batch_notes, category=category)
    return await _analyze_anthropic(image_bytes_list, batch_notes=batch_notes, category=category)
