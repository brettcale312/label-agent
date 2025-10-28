"""
search_gocollect_playwright_tool.py
-----------------------------------
LangGraph-compatible Playwright scraper for GoCollect.

✨ New Version:
    • Runs a Brave Search first to find the top GoCollect.com result.
    • Opens that URL dynamically via Playwright to extract FMV data.
    • Returns unified price fields (median_price, average_price) for agent use.

Requirements:
    pip install playwright aiohttp
    playwright install chromium
    export BRAVE_API_KEY=<your key>
"""

import asyncio
import re
import logging
from datetime import datetime, timezone
import aiohttp
from langchain_core.tools import tool
from playwright.async_api import async_playwright
import os

logger = logging.getLogger("GoCollectPlaywrightTool")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")


# -------------------------------------------------------------------------
#  Brave Search to find the top GoCollect link
# -------------------------------------------------------------------------
async def brave_find_gocollect_url(query: str) -> str | None:
    """Perform a Brave search and return the first GoCollect.com URL."""
    api_key = os.getenv("BRAVE_API_KEY")
    if not api_key:
        logger.warning("⚠️ BRAVE_API_KEY not set. Skipping Brave search.")
        return None

    url = "https://api.search.brave.com/res/v1/web/search"
    params = {"q": f"site:gocollect.com {query}", "count": 5}
    headers = {"Accept": "application/json", "X-Subscription-Token": api_key}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers) as r:
                if r.status != 200:
                    logger.warning(f"⚠️ Brave API returned status {r.status}")
                    return None
                data = await r.json()
                results = data.get("web", {}).get("results", [])
                for result in results:
                    link = result.get("url", "")
                    if "gocollect.com" in link:
                        logger.info(f"🔗 Found GoCollect URL via Brave: {link}")
                        return link
    except Exception as e:
        logger.error(f"❌ Brave search failed: {e}")
    return None


# -------------------------------------------------------------------------
#  Playwright scraper
# -------------------------------------------------------------------------
async def extract_fmv_from_page(url: str) -> dict:
    """Load a GoCollect page and extract FMV or numeric price values."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            logger.info(f"🌐 Visiting {url}")
            await page.goto(url, timeout=60000, wait_until="domcontentloaded")

            # Wait for the FMV or any dollar sign text to appear
            try:
                await page.wait_for_selector("text=FMV", timeout=10000)
            except Exception:
                logger.info("⌛ No explicit FMV selector; scanning full HTML...")

            html = await page.content()
            matches = re.findall(r"\$[\d,]+(?:\.\d{2})?", html)
            fmv_value = None
            if matches:
                cleaned = sorted({float(m.replace("$", "").replace(",", "")) for m in matches})
                if cleaned:
                    # Compute trimmed mean (ignore top/bottom outliers if many results)
                    if len(cleaned) > 4:
                        trimmed = cleaned[1:-1]
                        fmv_value = round(sum(trimmed) / len(trimmed), 2)
                    else:
                        fmv_value = round(sum(cleaned) / len(cleaned), 2)

            title = await page.title()

            return {
                "source": "GoCollect (Playwright)",
                "url": url,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "title": title,
                "sample_count": len(matches),
                "median_price": fmv_value,
                "average_price": fmv_value,
                "raw_prices": matches,
                "source_used": bool(fmv_value),
            }

        except Exception as e:
            logger.error(f"❌ Error scraping {url}: {e}")
            return {
                "source": "GoCollect (Playwright)",
                "url": url,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": str(e),
                "source_used": False,
            }
        finally:
            await browser.close()


# -------------------------------------------------------------------------
#  LangGraph Tool Entry
# -------------------------------------------------------------------------
@tool("search_gocollect_playwright_tool", return_direct=False)
async def search_gocollect_playwright_tool(query: str) -> dict:
    """
    Dynamically scrape GoCollect FMV using Playwright.

    1. Runs Brave search to find top GoCollect URL for the query.
    2. Loads that URL in headless Chromium.
    3. Extracts visible FMV or price-like values.
    """
    if query.startswith("http"):
        gocollect_url = query
    else:
        gocollect_url = await brave_find_gocollect_url(query)

    if not gocollect_url:
        logger.warning(f"⚠️ No GoCollect URL found for query '{query}'.")
        return {
            "source": "GoCollect (Playwright)",
            "query": query,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "median_price": None,
            "average_price": None,
            "sample_count": 0,
            "raw_prices": [],
            "source_used": False,
        }

    result = await extract_fmv_from_page(gocollect_url)
    logger.info(f"✅ Completed scrape for {query} | FMV: {result.get('median_price')}")
    return result


# -------------------------------------------------------------------------
#  Manual test entry
# -------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python search_gocollect_playwright_tool.py '<query or URL>'")
    else:
        asyncio.run(search_gocollect_playwright_tool(sys.argv[1]))
