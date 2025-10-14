"""
pricing_tools/scryfall.py
-------------------------
Lightweight wrapper for the Scryfall public API.

Provides price and metadata lookup for Magic: The Gathering cards.
No authentication or API key required.
"""

import aiohttp
import asyncio

BASE_URL = "https://api.scryfall.com"


async def get_scryfall_price(card_name: str) -> dict:
    """
    Fetch price and basic metadata for a Magic: The Gathering card.

    Args:
        card_name (str): The full or partial name of the card.

    Returns:
        dict: {
            "title": str,
            "set": str,
            "rarity": str,
            "usd": float or None,
            "usd_foil": float or None,
            "image_url": str,
            "source": "Scryfall"
        }
        or {} if not found.
    """
    url = f"{BASE_URL}/cards/named"
    params = {"fuzzy": card_name}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()

        return {
            "title": data.get("name"),
            "set": data.get("set_name"),
            "rarity": data.get("rarity"),
            "usd": float(data["prices"]["usd"]) if data["prices"]["usd"] else None,
            "usd_foil": float(data["prices"]["usd_foil"]) if data["prices"]["usd_foil"] else None,
            "image_url": data["image_uris"]["normal"] if "image_uris" in data else None,
            "source": "Scryfall",
        }

    except Exception as e:
        print(f"[Scryfall] Error fetching '{card_name}': {e}")
        return {}


# --- Quick local test ---
if __name__ == "__main__":
    async def test():
        result = await get_scryfall_price("Ragavan, Nimble Pilferer")
        print(result)

    asyncio.run(test())
