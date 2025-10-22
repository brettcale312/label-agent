# LEGACY MODULE — DO NOT USE
raise ImportError("pricing_model.py is deprecated. Use LangGraph PricingAgent instead.")


# import logging
# from decimal import Decimal
# from typing import Optional, Dict, Any
# import asyncio
# import base64
# import os
# import json
# from datetime import datetime

# # Search and pricing imports
# from pricing_tools.brave_search import get_brave_price as get_web_price
# from pricing_tools.valuation_logic import (
#     estimate_value,
#     round_retail,
#     calculate_comic_price,
#     calculate_card_price,
#     apply_condition_multiplier,
# )
# from utils.logger import get_logger

# logger = get_logger("pricing_model")

# # === Debug + JSONL Logging Config ===
# DEBUG_LOGS = os.getenv("DEBUG_LOGS", "true").lower() in ("1", "true", "yes")
# LOG_DIR = "logs"
# os.makedirs(LOG_DIR, exist_ok=True)


# def _safe_run_async(coro):
#     """Safely run async coroutine, handling existing event loop."""
#     import nest_asyncio
#     nest_asyncio.apply()
#     return asyncio.run(coro)


# def _safe_get_discogs_data(title: str, artist: str = None):
#     """Synchronous Discogs pricing using requests - returns full data structure."""
#     try:
#         import requests
#         DISCOGS_TOKEN = os.getenv("DISCOGS_TOKEN")
#         if not DISCOGS_TOKEN:
#             logger.warning("No DISCOGS_TOKEN found")
#             return {}
#         query = f"{title} {artist or ''}".strip()
#         url = "https://api.discogs.com/database/search"
#         params = {"q": query, "type": "release", "per_page": 10}
#         headers = {"Authorization": f"Discogs token={DISCOGS_TOKEN}", "User-Agent": "pricing-agent/1.0"}
#         response = requests.get(url, params=params, headers=headers, timeout=10)
#         if response.status_code != 200:
#             return {}
#         data = response.json()
#         results = data.get("results", [])
#         if not results:
#             return {}
#         release_id = results[0].get("id")
#         if not release_id:
#             return {}
#         stats_url = f"https://api.discogs.com/marketplace/stats/{release_id}"
#         stats_response = requests.get(stats_url, headers=headers, timeout=10)
#         if stats_response.status_code != 200:
#             return {}
#         stats = stats_response.json()
#         return {
#             "median_price": stats.get("price", {}).get("median"),
#             "lowest_price": stats.get("lowest_price", {}).get("value"),
#             "num_for_sale": stats.get("num_for_sale", 0),
#             "release_id": release_id,
#             "title": results[0].get("title", title),
#         }
#     except Exception as e:
#         logger.error(f"[Discogs] Error in sync wrapper: {e}")
#         return {}


# def _safe_get_ebay_data(title: str, category: str = None, metadata: dict = None):
#     """Synchronous eBay pricing using requests - returns full data structure."""
#     try:
#         import requests
#         from statistics import median, mean

#         EBAY_APP_ID = os.getenv("EBAY_APP_ID") or os.getenv("EBAY_CLIENT_ID")
#         EBAY_CERT_ID = os.getenv("EBAY_CERT_ID") or os.getenv("EBAY_CLIENT_SECRET")
#         EBAY_REFRESH_TOKEN = os.getenv("EBAY_REFRESH_TOKEN")
#         if not all([EBAY_APP_ID, EBAY_CERT_ID, EBAY_REFRESH_TOKEN]):
#             logger.warning("Missing eBay credentials")
#             return {}

#         token_url = "https://api.ebay.com/identity/v1/oauth2/token"
#         auth_header = f"Basic {base64.b64encode(f'{EBAY_APP_ID}:{EBAY_CERT_ID}'.encode()).decode()}"
#         token_data = {
#             "grant_type": "refresh_token",
#             "refresh_token": EBAY_REFRESH_TOKEN,
#             "scope": "https://api.ebay.com/oauth/api_scope",
#         }
#         token_headers = {"Content-Type": "application/x-www-form-urlencoded", "Authorization": auth_header}
#         token_response = requests.post(token_url, data=token_data, headers=token_headers, timeout=10)
#         if token_response.status_code != 200:
#             logger.warning(f"eBay token error: {token_response.status_code}")
#             return {}
#         access_token = token_response.json()["access_token"]

#         query_parts = [title]
#         if metadata:
#             if metadata.get("set"):
#                 query_parts.append(metadata["set"])
#             if metadata.get("number"):
#                 query_parts.append(metadata["number"])
#             if metadata.get("rarity"):
#                 rarity_text = (
#                     "Holo Rare" if metadata.get("holo") else "Rare" if metadata["rarity"] == "★" else ""
#                 )
#                 if rarity_text:
#                     query_parts.append(rarity_text)
#             if metadata.get("year"):
#                 query_parts.append(str(metadata["year"]))
#         elif category:
#             query_parts.append(category)

#         query = " ".join(query_parts)

#         search_url = "https://api.ebay.com/buy/browse/v1/item_summary/search"
#         search_params = {"q": query, "limit": "20", "filter": "buyingOptions:FIXED_PRICE"}
#         search_headers = {
#             "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
#             "Authorization": f"Bearer {access_token}",
#             "Accept": "application/json",
#         }
#         response = requests.get(search_url, params=search_params, headers=search_headers, timeout=10)
#         if response.status_code != 200:
#             logger.warning(f"eBay search error: {response.status_code}")
#             return {}
#         items = response.json().get("itemSummaries", [])
#         if not items:
#             return {}

#         prices = [float(item.get("price", {}).get("value", 0)) for item in items if item.get("price")]
#         if not prices:
#             return {}
#         return {
#             "median_active_price": median(prices),
#             "avg_active_price": mean(prices),
#             "sample_count": len(prices),
#             "query": query,
#         }
#     except Exception as e:
#         logger.error(f"[eBay] Error in sync wrapper: {e}")
#         return {}


# def _normalize_price(value: Any) -> Optional[Decimal]:
#     """Convert and sanitize numeric price strings or floats to Decimal."""
#     try:
#         if value is None:
#             return None
#         if isinstance(value, str):
#             value = value.replace("$", "").replace(",", "").strip()
#         val = Decimal(value)
#         return val if val > 0 else None
#     except Exception:
#         return None


# def get_best_price(
#     title: str,
#     artist: Optional[str] = None,
#     category: str = "general",
#     condition: str = "vg",
#     venue: str = "antique_store",
#     metadata: Optional[dict] = None,
# ) -> Dict[str, Any]:
#     """Enhanced price aggregator using valuation logic and optional metadata."""
#     logger.info(f"Starting enhanced price lookup for: {title} | {artist or 'N/A'} | venue: {venue}")

#     # === Discogs (records/media only) ===
#     discogs_data = {}
#     is_record_media = category.lower() in ["record", "vinyl", "media", "cd", "cassette", "tape"]
#     if is_record_media:
#         discogs_data = _safe_get_discogs_data(title, artist)
#         if discogs_data:
#             logger.info(
#                 f"Discogs: median=${discogs_data.get('median_price', 0)}, "
#                 f"lowest=${discogs_data.get('lowest_price', 0)}, "
#                 f"for_sale={discogs_data.get('num_for_sale', 0)}"
#             )

#     # === eBay ===
#     ebay_data = _safe_get_ebay_data(title, category, metadata)
#     ebay_median = ebay_data.get("median_active_price", 0) if ebay_data else 0
#     ebay_warnings = ebay_data.get("validation_warnings", []) if ebay_data else []
#     if ebay_median:
#         logger.info(
#             f"eBay: median=${ebay_median:.2f}, avg=${ebay_data.get('avg_active_price', 0):.2f}, "
#             f"samples={ebay_data.get('sample_count', 0)}"
#         )
#         if ebay_warnings:
#             logger.warning(f"eBay validation warnings: {ebay_warnings}")

#     # === Records: use human-accurate valuation ===
#     if discogs_data and is_record_media and (
#         discogs_data.get("median_price") or discogs_data.get("lowest_price")
#     ):
#         item_meta = {"title": title, "condition": condition, "venue": venue, "category": category}
#         try:
#             valuation_result = estimate_value(discogs_data, ebay_data, item_meta)
#             return {
#                 "sources": {
#                     "Discogs": discogs_data.get("median_price", 0),
#                     "eBay": ebay_data.get("median_active_price", 0),
#                 },
#                 "final_price": valuation_result["estimated_price"],
#                 "base_price": ebay_data.get("median_active_price", 0),
#                 "reasoning": valuation_result["reasoning"],
#                 "method": "human-accurate_valuation",
#             }
#         except Exception as e:
#             logger.error(f"Valuation logic failed: {e}")
#             return {
#                 "sources": {"Discogs": discogs_data.get("median_price", 0)},
#                 "final_price": discogs_data.get("median_price", 0),
#                 "method": "discogs_fallback",
#             }

#     # === Web fallback ===
#     sources = {}
#     if ebay_median:
#         sources["eBay"] = ebay_median
#     try:
#         web_price = get_web_price(title)
#         p = _normalize_price(web_price)
#         if p:
#             sources["WebSearch"] = float(p)
#     except Exception as e:
#         logger.warning(f"Web search failed: {e}")

#     if not sources:
#         logger.warning(f"No valid prices found for: {title}")
#         return {"sources": {}, "final_price": None, "note": "No prices found", "method": "none"}

#     # === Weighted average ===
#     weights = {"eBay": 0.75, "WebSearch": 0.25}
#     active_weights = {k: weights[k] for k in sources.keys() if k in weights}
#     weighted_sum = sum(sources[k] * active_weights[k] for k in active_weights)
#     weighted_avg = round(weighted_sum / sum(active_weights.values()), 2)
#     base_price = ebay_median or weighted_avg
#     final_price = base_price
#     reasoning = ""

#     # === Comic pricing ===
#     if category.lower() == "comic":
#         import re
#         year_match = re.search(r"\b(19|20)\d{2}\b", title)
#         year = int(year_match.group()) if year_match else None
#         ebay_base_price = ebay_median or weighted_avg
#         final_price = calculate_comic_price(ebay_base_price, condition, year)
#         reasoning = (
#             f"Base eBay median ${ebay_base_price:.2f} -> comic pricing logic applied ({condition})."
#         )
        
#         # Add validation warnings to reasoning
#         if ebay_warnings:
#             reasoning += f" WARNING: {', '.join(ebay_warnings)}"

#     # === Card pricing ===
#     elif "pokemon" in title.lower() or "mtg" in title.lower() or category.lower() in [
#         "card",
#         "trading_card",
#         "pokemon",
#     ]:
#         rarity = metadata.get("rarity") if metadata else None
#         year = metadata.get("year") if metadata else None
#         final_price = calculate_card_price(base_price, condition, rarity, year, venue)
#         if base_price and final_price:
#             if abs(final_price - base_price) < 0.05:
#                 reasoning = f"Base eBay median ${base_price:.2f} used directly (condition already reflected in market)."
#             elif final_price < base_price:
#                 reasoning = f"Base eBay median ${base_price:.2f} adjusted for visible wear -> ${final_price:.2f} booth price."
#             else:
#                 reasoning = f"Base eBay median ${base_price:.2f} rounded for booth display -> ${final_price:.2f}."
#         else:
#             reasoning = "No reliable price data; used adjusted rarity floor."

#     # === Everything else ===
#     else:
#         adjusted_price = apply_condition_multiplier(weighted_avg, condition)
#         if venue == "antique_store":
#             if weighted_avg < 5:
#                 final_price = adjusted_price * 2.5
#             elif weighted_avg < 10:
#                 final_price = adjusted_price * 1.75
#             else:
#                 final_price = adjusted_price * 1.2
#             final_price = round_retail(final_price, venue)
#         else:
#             final_price = apply_condition_multiplier(weighted_avg, condition)
#         reasoning = f"Weighted average ${weighted_avg:.2f} × venue/condition = ${final_price:.2f}"

#     # === JSONL debug logging ===
#     if DEBUG_LOGS:
#         try:
#             log_file = os.path.join(LOG_DIR, f"pricing_results_{datetime.now():%Y-%m-%d}.jsonl")
#             entry = {
#                 "timestamp": datetime.now().isoformat(timespec="seconds"),
#                 "title": title,
#                 "category": category,
#                 "condition": condition,
#                 "venue": venue,
#                 "sources": sources,
#                 "base_price": float(base_price),
#                 "final_price": float(final_price),
#                 "reasoning": reasoning,
#                 "method": "enhanced_pricing",
#             }
#             with open(log_file, "a", encoding="utf-8") as f:
#                 f.write(json.dumps(entry) + "\n")
#         except Exception as e:
#             logger.warning(f"Failed to write pricing log: {e}")

#     return {
#         "sources": sources,
#         "base_price": base_price,
#         "final_price": final_price,
#         "reasoning": reasoning,
#         "method": "enhanced_pricing",
#     }


# if __name__ == "__main__":
#     import sys
#     args = sys.argv[1:]
#     title = args[0] if args else "Funko Pop Darth Vader"
#     artist = args[1] if len(args) > 1 else None
#     result = get_best_price(title, artist=artist)
#     print(result)
