import logging
from decimal import Decimal
from typing import Optional, Dict, Any

from pricing_tools.discogs import get_discogs_price
from pricing_tools.ebay import get_ebay_price
#from pricing_tools.duckduckgo_search import get_duckduckgo_price as get_web_price
from pricing_tools.brave_search import get_brave_price as get_web_price

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def _normalize_price(value: Any) -> Optional[Decimal]:
    """Convert and sanitize numeric price strings or floats to Decimal."""
    try:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.replace("$", "").replace(",", "").strip()
        val = Decimal(value)
        return val if val > 0 else None
    except Exception:
        return None


def get_best_price(title: str, artist: Optional[str] = None, category: str = "general") -> Dict[str, Any]:
    """
    Deterministic price aggregator:
      - Use Discogs if it returns a valid price (records/media)
      - Otherwise, combine eBay (0.75) + Web (0.25)
    """
    sources = {}

    logger.info(f"Starting price lookup for: {title} | {artist or 'N/A'}")

    # --- Discogs ---
    discogs_price = None
    try:
        discogs_price = get_discogs_price(title, artist)
        p = _normalize_price(discogs_price)
        if p:
            sources["Discogs"] = p
            logger.info(f"Discogs: ${float(p):.2f}")
    except Exception as e:
        logger.warning(f"Discogs lookup failed: {e}")

    # 🎯 If Discogs found something, treat it as authoritative
    if "Discogs" in sources:
        logger.info("Discogs result found — skipping eBay/Web.")
        return {
            "sources": {"Discogs": float(sources['Discogs'])},
            "final_price": float(sources["Discogs"]),
            "note": "Discogs authoritative source used."
        }

    # --- eBay ---
    try:
        ebay_price = get_ebay_price(title, category)
        p = _normalize_price(ebay_price)
        if p:
            sources["eBay"] = p
            logger.info(f"eBay: ${float(p):.2f}")
    except Exception as e:
        logger.warning(f"eBay lookup failed: {e}")

    # --- Web Search ---
    try:
        web_price = get_web_price(title)
        p = _normalize_price(web_price)
        if p:
            sources["WebSearch"] = p
            logger.info(f"WebSearch: ${float(p):.2f}")
    except Exception as e:
        logger.warning(f"Web search failed: {e}")

    # --- Weighted fallback (no Discogs) ---
    if sources:
        weights = {"eBay": 0.75, "WebSearch": 0.25}
        active_weights = {k: weights[k] for k in sources.keys() if k in weights}
        total_w = sum(active_weights.values())
        weighted_sum = sum(float(sources[k]) * active_weights[k] for k in active_weights)
        weighted_avg = round(weighted_sum / total_w, 2) if total_w > 0 else None

        result = {
            "sources": {k: float(v) for k, v in sources.items()},
            "final_price": weighted_avg,
        }
        logger.info(f"Weighted average from {len(sources)} sources: ${weighted_avg}")
        return result

    # --- None found ---
    logger.warning(f"No valid prices found for: {title}")
    return {"sources": {}, "final_price": None, "note": "No prices found"}


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    title = args[0] if args else "Funko Pop Darth Vader"
    artist = args[1] if len(args) > 1 else None

    result = get_best_price(title, artist=artist)
    print(result)
