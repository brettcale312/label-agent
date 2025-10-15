import re
import requests
from bs4 import BeautifulSoup
from statistics import mean


def get_duckduckgo_price(title: str):
    """
    Live web search via DuckDuckGo HTML (no API key).
    Scans the first page of results, finds all price-like values,
    filters outliers, and averages them for a more reliable estimate.
    """
    print(f"[DuckDuckGo] Searching web for {title}")
    try:
        # Build search query
        query = f"{title} site:ebay.com OR site:discogs.com price"
        url = f"https://duckduckgo.com/html/?q={requests.utils.quote(query)}"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }

        # Request page
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        # Parse text content
        soup = BeautifulSoup(response.text, "html.parser")
        text = soup.get_text(" ", strip=True)

        # Find all prices in the text
        matches = re.findall(r"\$\s?(\d{1,4}(?:[.,]\d{2})?)", text)
        prices = []

        for m in matches:
            try:
                value = float(m.replace(",", ""))
                if 2 <= value <= 1000:  # filter out $0.99, crazy values, etc.
                    prices.append(value)
            except ValueError:
                continue

        if not prices:
            print("[DuckDuckGo] No valid prices found in search results")
            return None

        # Optionally filter outliers
        avg_price = round(mean(prices), 2)
        print(f"[DuckDuckGo] Found {len(prices)} price samples, avg ≈ ${avg_price}")
        return avg_price

    except Exception as e:
        print(f"[DuckDuckGo] Error: {e}")
        return None
