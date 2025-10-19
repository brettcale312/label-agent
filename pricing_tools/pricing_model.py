import logging
from decimal import Decimal
from typing import Optional, Dict, Any
import asyncio
import base64

# DuckDuckGo search - planned for future use, currently using Brave Search
#from pricing_tools.duckduckgo_search import get_duckduckgo_price as get_web_price
from pricing_tools.brave_search import get_brave_price as get_web_price
from pricing_tools.valuation_logic import estimate_value, round_retail, calculate_comic_price
from utils.logger import get_logger

logger = get_logger("pricing_model")


def _safe_run_async(coro):
    """Safely run async coroutine, handling existing event loop."""
    import nest_asyncio
    nest_asyncio.apply()
    return asyncio.run(coro)


def _safe_get_discogs_data(title: str, artist: str = None):
    """Synchronous Discogs pricing using requests - returns full data structure."""
    try:
        import requests
        import os
        
        DISCOGS_TOKEN = os.getenv("DISCOGS_TOKEN")
        if not DISCOGS_TOKEN:
            logger.warning("No DISCOGS_TOKEN found")
            return {}
            
        query = f"{title} {artist or ''}".strip()
        url = "https://api.discogs.com/database/search"
        params = {"q": query, "type": "release", "per_page": 10}
        headers = {
            "Authorization": f"Discogs token={DISCOGS_TOKEN}",
            "User-Agent": "pricing-agent/1.0"
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=10)
        if response.status_code != 200:
            logger.warning(f"Discogs API error: {response.status_code}")
            return {}
            
        data = response.json()
        results = data.get("results", [])
        if not results:
            return {}
            
        # Get the first result's marketplace stats
        release_id = results[0].get("id")
        if not release_id:
            return {}
            
        stats_url = f"https://api.discogs.com/marketplace/stats/{release_id}"
        stats_response = requests.get(stats_url, headers=headers, timeout=10)
        if stats_response.status_code != 200:
            return {}
            
        stats = stats_response.json()
        
        # Extract comprehensive data
        median_price = stats.get("price", {}).get("median")
        lowest_price = stats.get("lowest_price", {}).get("value")
        num_for_sale = stats.get("num_for_sale", 0)
        
        return {
            "median_price": median_price,
            "lowest_price": lowest_price,
            "num_for_sale": num_for_sale,
            "release_id": release_id,
            "title": results[0].get("title", title)
        }
        
    except Exception as e:
        logger.error(f"[Discogs] Error in sync wrapper: {e}")
        return {}

def _safe_get_discogs_price(title: str, artist: str = None):
    """Legacy wrapper for backward compatibility."""
    data = _safe_get_discogs_data(title, artist)
    return data.get("median_price") or data.get("lowest_price")


def _safe_get_ebay_data(title: str, category: str = None):
    """Synchronous eBay pricing using requests - returns full data structure."""
    try:
        import requests
        import os
        from statistics import median, mean
        
        EBAY_APP_ID = os.getenv("EBAY_APP_ID") or os.getenv("EBAY_CLIENT_ID")
        EBAY_CERT_ID = os.getenv("EBAY_CERT_ID") or os.getenv("EBAY_CLIENT_SECRET")
        EBAY_REFRESH_TOKEN = os.getenv("EBAY_REFRESH_TOKEN")
        
        if not all([EBAY_APP_ID, EBAY_CERT_ID, EBAY_REFRESH_TOKEN]):
            logger.warning("Missing eBay credentials")
            return {}
            
        # Get access token
        token_url = "https://api.ebay.com/identity/v1/oauth2/token"
        auth_header = f"Basic {base64.b64encode(f'{EBAY_APP_ID}:{EBAY_CERT_ID}'.encode()).decode()}"
        token_data = {
            "grant_type": "refresh_token",
            "refresh_token": EBAY_REFRESH_TOKEN,
            "scope": "https://api.ebay.com/oauth/api_scope"
        }
        token_headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": auth_header
        }
        
        token_response = requests.post(token_url, data=token_data, headers=token_headers, timeout=10)
        if token_response.status_code != 200:
            logger.warning(f"eBay token error: {token_response.status_code}")
            return {}
            
        access_token = token_response.json()["access_token"]
        
        # Search eBay
        query = f"{title} {category or ''}".strip()
        search_url = "https://api.ebay.com/buy/browse/v1/item_summary/search"
        search_params = {
            "q": query,
            "limit": "20",
            "filter": "buyingOptions:FIXED_PRICE"
        }
        search_headers = {
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json"
        }
        
        search_response = requests.get(search_url, params=search_params, headers=search_headers, timeout=10)
        if search_response.status_code != 200:
            logger.warning(f"eBay search error: {search_response.status_code}")
            return {}
            
        search_data = search_response.json()
        items = search_data.get("itemSummaries", [])
        if not items:
            return {}
            
        prices = []
        for item in items:
            try:
                price = float(item.get("price", {}).get("value", 0))
                if price > 0:
                    prices.append(price)
            except:
                continue
                
        if not prices:
            return {}
            
        return {
            "median_active_price": median(prices),
            "avg_active_price": mean(prices),
            "sample_count": len(prices),
            "query": query
        }
        
    except Exception as e:
        logger.error(f"[eBay] Error in sync wrapper: {e}")
        return {}

def _safe_get_ebay_price(title: str, category: str = None):
    """Legacy wrapper for backward compatibility."""
    data = _safe_get_ebay_data(title, category)
    return data.get("median_active_price")


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


def get_best_price(title: str, artist: Optional[str] = None, category: str = "general", 
                  condition: str = "vg", venue: str = "antique_store") -> Dict[str, Any]:
    """
    Enhanced price aggregator using human-accurate valuation logic:
      - For records/media: Use Discogs + eBay with valuation logic
      - For other items: Use eBay + Web search with weighted average
    """
    logger.info(f"Starting enhanced price lookup for: {title} | {artist or 'N/A'} | venue: {venue}")

    # --- Get comprehensive data from Discogs (only for records/media) ---
    discogs_data = {}
    if category.lower() in ["record", "vinyl", "media", "cd", "cassette", "tape"]:
        try:
            discogs_data = _safe_get_discogs_data(title, artist)
            if discogs_data:
                median_price = discogs_data.get('median_price') or 0
                lowest_price = discogs_data.get('lowest_price') or 0
                num_for_sale = discogs_data.get('num_for_sale', 0)
                logger.info(f"Discogs: median=${median_price:.2f}, "
                           f"lowest=${lowest_price:.2f}, "
                           f"for_sale={num_for_sale}")
        except Exception as e:
            logger.warning(f"Discogs lookup failed: {e}")
    else:
        logger.info(f"Skipping Discogs lookup for {category} - not a record/media item")

    # --- Get comprehensive data from eBay ---
    ebay_data = {}
    ebay_median = None  # Store the eBay median separately
    try:
        ebay_data = _safe_get_ebay_data(title, category)
        if ebay_data:
            ebay_median = ebay_data.get('median_active_price', 0)
            logger.info(f"eBay: median=${ebay_median:.2f}, "
                       f"avg=${ebay_data.get('avg_active_price', 0):.2f}, "
                       f"samples={ebay_data.get('sample_count', 0)}")
    except Exception as e:
        logger.warning(f"eBay lookup failed: {e}")

    # 🎯 If we have Discogs data AND it's a record/media item, use human-accurate valuation logic
    # Only records should use Discogs - comics, cards, and anything should skip Discogs entirely
    is_record_media = category.lower() in ["record", "vinyl", "media", "cd", "cassette", "tape"]
    if discogs_data and (discogs_data.get("median_price") or discogs_data.get("lowest_price")) and is_record_media:
        logger.info("Using human-accurate valuation logic for record/media item")
        
        item_meta = {
            "title": title,
            "condition": condition,
            "venue": venue,
            "category": category
        }
        
        try:
            valuation_result = estimate_value(discogs_data, ebay_data, item_meta)
            logger.info(f"Valuation result: ${valuation_result['estimated_price']:.2f} - {valuation_result['reasoning']}")
            
            return {
                "sources": {
                    "Discogs": discogs_data.get("median_price", 0),
                    "eBay": ebay_data.get("median_active_price", 0)
                },
                "final_price": valuation_result["estimated_price"],
                "reasoning": valuation_result["reasoning"],
                "method": "human-accurate_valuation"
            }
        except Exception as e:
            logger.error(f"Valuation logic failed: {e}")
            # Fall back to simple Discogs median
            return {
                "sources": {"Discogs": discogs_data.get("median_price", 0)},
                "final_price": discogs_data.get("median_price", 0),
                "method": "discogs_fallback"
            }

    # --- Fallback for non-record items: eBay + Web Search ---
    sources = {}
    
    # eBay
    if ebay_data and ebay_data.get("median_active_price"):
        sources["eBay"] = ebay_data["median_active_price"]
        logger.info(f"eBay: ${ebay_data['median_active_price']:.2f}")

    # Web Search
    try:
        web_price = get_web_price(title)
        p = _normalize_price(web_price)
        if p:
            sources["WebSearch"] = float(p)
            logger.info(f"WebSearch: ${float(p):.2f}")
    except Exception as e:
        logger.warning(f"Web search failed: {e}")

    # Weighted average for non-record items
    if sources:
        weights = {"eBay": 0.75, "WebSearch": 0.25}
        active_weights = {k: weights[k] for k in sources.keys() if k in weights}
        total_w = sum(active_weights.values())
        weighted_sum = sum(sources[k] * active_weights[k] for k in active_weights)
        weighted_avg = round(weighted_sum / total_w, 2) if total_w > 0 else None
        
        # Apply specialized pricing logic based on item type
        if venue == "antique_store" and weighted_avg:
            logger.info(f"DEBUG: category='{category}', category.lower()='{category.lower()}'")
            if category.lower() == "comic":
                # Use specialized comic pricing logic
                # Extract year from title if possible (basic pattern matching)
                year = None
                import re
                year_match = re.search(r'\b(19|20)\d{2}\b', title)
                if year_match:
                    year = int(year_match.group())
                
                # Use the captured eBay median as base price
                ebay_base_price = ebay_median or weighted_avg
                
                logger.info(f"DEBUG: ebay_median=${ebay_median:.2f}")
                logger.info(f"DEBUG: weighted_avg=${weighted_avg:.2f}")
                logger.info(f"DEBUG: ebay_base_price=${ebay_base_price:.2f}")
                
                final_price = calculate_comic_price(ebay_base_price, condition, year)
                logger.info(f"Comic pricing: ebay_base=${ebay_base_price:.2f}, condition={condition}, year={year}, final=${final_price:.2f}")
                
                # Add base price info to the result for frontend consistency
                result = {
                    "sources": sources,
                    "final_price": final_price,
                    "base_price": ebay_base_price,  # Store the actual eBay median as base price
                    "method": "comic_pricing"
                }
                logger.info(f"DEBUG: Returning result with base_price=${result['base_price']:.2f}")
                return result
            else:
                # Apply standard condition and venue multipliers for non-comic items
                from pricing_tools.valuation_logic import apply_condition_multiplier
                condition_adjusted_price = apply_condition_multiplier(weighted_avg, condition)
                
                # Then apply venue multiplier
                if weighted_avg < 5:
                    final_price = condition_adjusted_price * 2.5
                elif weighted_avg < 10:
                    final_price = condition_adjusted_price * 1.75
                else:
                    final_price = condition_adjusted_price * 1.2
                
                # Then apply rounding
                final_price = round_retail(final_price, venue)
        else:
            # Apply condition multiplier but no venue multiplier
            from pricing_tools.valuation_logic import apply_condition_multiplier
            final_price = apply_condition_multiplier(weighted_avg, condition)

        result = {
            "sources": sources,
            "final_price": final_price,
            "method": "weighted_average"
        }
        logger.info(f"Weighted average from {len(sources)} sources: ${weighted_avg} -> ${final_price} (antique store adjusted)")
        return result

    # --- None found ---
    logger.warning(f"No valid prices found for: {title}")
    return {"sources": {}, "final_price": None, "note": "No prices found", "method": "none"}


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    title = args[0] if args else "Funko Pop Darth Vader"
    artist = args[1] if len(args) > 1 else None

    result = get_best_price(title, artist=artist)
    print(result)
