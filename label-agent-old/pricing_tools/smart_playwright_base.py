"""
smart_playwright_base.py
------------------------
Reusable Playwright helpers for Brave/smart search + scraping.
"""

import re
import logging
from playwright.async_api import async_playwright
from .smart_search import smart_search
from .value_cleaners import sanitize_prices

logger = logging.getLogger("SmartPlaywrightBase")


async def find_url(domain: str, query: str, count: int = 5) -> str | None:
    """Use SmartSearch to find a relevant URL on a specific domain."""
    try:
        if hasattr(smart_search, "arun"):
            results = await smart_search.arun(f"site:{domain} {query}")
        else:
            results = await smart_search(f"site:{domain} {query}", count=count)

        if not results:
            logger.warning(f"⚠️ No SmartSearch results for {domain}")
            return None

        if isinstance(results, dict) and "results" in results:
            results = results["results"]

        for r in results:
            if isinstance(r, str) and domain.lower() in r.lower():
                return r
            elif isinstance(r, dict):
                url = r.get("url", "")
                if domain.lower() in url.lower():
                    return url
    except Exception as e:
        logger.error(f"❌ SmartSearch lookup failed for {domain}: {e}")
    return None


async def scrape_page(url: str, pattern: str = r"\$[\d,]+(?:\.\d{2})?") -> dict:
    """
    Visit a URL with Playwright and extract all price-like strings.
    Automatically sanitizes results via value_cleaners.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        logger.info(f"🌐 Visiting {url}")
        await page.goto(url, timeout=60000, wait_until="domcontentloaded")
        html = await page.content()
        matches = re.findall(pattern, html)

        cleaned = sorted({
            float(m.replace("$", "").replace(",", ""))
            for m in matches if re.search(r"\d", m)
        })

        cleaned = sanitize_prices(cleaned, query=url)

        median = round(sum(cleaned) / len(cleaned), 2) if cleaned else None
        avg = round(sum(cleaned) / len(cleaned), 2) if cleaned else None

        await browser.close()

        return {
            "source_url": url,
            "sample_count": len(cleaned),
            "median_price": median,
            "average_price": avg,
            "raw_prices": cleaned,
        }
