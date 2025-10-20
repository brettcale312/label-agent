# 🧠 Project Overview — Label Agent / Pricing AI Integration

 _This repository is a multi-agent Python app integrating scanning and pricing modules. Focus on connecting `app/vision.py` with `pricing_tools/pricing_model.py`._

## 🎯 Purpose
This project automates **pricing and labeling** for collectibles, media, and retail items such as comics, vinyl records, trading cards, and Funko Pops.

The app uses scanning (barcode or image-based recognition) to identify an item, determines its category, and retrieves **real-time market prices** from multiple sources.  
It then applies custom rounding and formatting rules before sending the data to label generation or inventory management systems.

---

## 🏗️ Current Architecture
label-agent/
│
├── app/
│ ├── main.py → Flask / scanning entry point
│ ├── pricing.py → rounding & formatting logic for labels
│ ├── sandpiper.py → export / integration with Sandpiper or sheets
│ ├── sheets.py, vision.py → scanning and OCR functionality
│
├── pricing_tools/
│ ├── discogs.py → async Discogs API wrapper (records)
│ ├── ebay.py → async eBay Browse API wrapper (general items)
│ ├── brave_search.py → Brave Search fallback (JSON web results)
│ ├── pricing_model.py → deterministic multi-source orchestrator
│
├── ebay_utils/
│ ├── auth.py → handles OAuth and token refresh for eBay
│
├── logs/ → per-tool logging
└── .env → contains API keys and tokens

---

## ⚙️ Pricing Model

The core logic lives in `pricing_tools/pricing_model.py`.  
It aggregates data from multiple providers:

### 1. Discogs
- Used for vinyl, CDs, or other music media.
- Returns the **lowest** or **median** market price.
- If Discogs finds a valid result, it’s prioritized.

### 2. eBay Browse API
- Searches active “Buy It Now” listings.
- Computes **median** and **average** of valid listings.
- Used for most non-record items (toys, collectibles, etc.).

### 3. Brave (or DuckDuckGo) Search
- Fallback if both APIs return nothing.
- Parses price patterns (e.g., `$29.99`, `USD 12.50`) from search snippets.

### 4. Aggregation Logic
- If Discogs returns a result → use **only Discogs**.
- Otherwise → weighted average of remaining sources  
  (eBay weighted more heavily than web results).
- Output example:

```json
{
  "sources": {
    "Discogs": 10.32,
    "eBay": 30.81
  },
  "weighted_average": 17.15
}

🔄 Planned Integration — Scanning + Pricing

Next, the pricing model will be connected to the scanning system in app/vision.py or app/main.py.

Planned flow:

When a scan completes, the item is identified:

{"title": "Funko Pop Darth Vader", "category": "toys"}


Pass that info to the pricing model:

from pricing_tools.pricing_model import get_best_price
from app.pricing import apply_rounding

price_info = get_best_price(title, category)
rounded = apply_rounding(price_info["final_price"])


Attach the result:

record["Suggested Price"] = rounded
record["Sources"] = price_info["sources"]
record["Note"] = price_info.get("note", "")


Send the enriched record to Sandpiper, Google Sheets, or label printing.

🔒 Environment Variables
Variable	Description
DISCOGS_TOKEN	Personal access token for Discogs API
BRAVE_API_KEY	API key for Brave search (web fallback)
DEBUG_LOGS	Set true for verbose logging
eBay OAuth handled dynamically	via ebay_utils/auth.py
🧩 Integration Plan in Cursor

Inside Cursor, the immediate task is to:

Locate the scan handler in app/main.py (the code that receives scanned item data).

Import get_best_price() and call it using the recognized title.

Return or display the suggested price and sources.

Cursor can then use this context to help auto-generate the integration code and suggest improvements.

🚀 Next Steps

 Attach pricing model to the scan recognition workflow.

 Cache results locally for faster repeated lookups.

 Add confidence scoring (based on number of listings or data source reliability).

 Enhance web search with structured data (schema.org price scraping).

💡 Quick Summary

“Scan → Identify → Fetch Market Prices → Round → Label or Export.”

This project blends AI-assisted product recognition with real-time pricing intelligence to power a seamless, automated labeling workflow.

In my words...
I have a booth at an antique store that uses Sandpiper as an inventory system. I sell a lot of things where you are trying to price and add a lot of them into the system quickly. At first I was uploading pictures to chatGPT and it would give me a price, etc. in a format that I could copy into a google sheet. I could then take that data and import it to sandpiper. Once imported, I could have it create barcode numbers for them and I export them back to the google sheet. I then had written another tool that could format those in a particular way to print on my rollo printer on 2x2 labels for cards and 4x3 labels for comics/records which also had the scannable barcode. So it was a few sales type bullets then the price and barcode.

I then wanted to automate all that into one flow. I take a picture on my phone and an iOS shortcut calls the code in the app folder. The vision.py creates some sales bullets, estimates a price and then presents it on a page for me to change/approve on my phone. Then one I do that, it calls the sandpiper api to add it to my stores inventory and return a barcode I can use on my custom labels.

The problem is, the price is not nearly as close as when I let chatGPT just analyze the pictures. I guess because the openapi model does not have a web search out of the box. We then began building tools to help with the price (pricing_tools). We have the ebay api and discogs api returning data. We got duckduckgo to kind of work, but it never returns a price. So we tried brave next. It also does not get prices so far, but does connect to the web. I also have a keepa api key and we plan on doing scryfall as well for MTG cards. To start with, we can use some logic to go in order from best to worst in getting the price logically. Ultimately, I probably want to use langchain or langgraph and just give it these tools to use.

I do plan on using the keepa and scryfall tools in the future, but we were going to first try connecting what we have so far to the original label agent. The idea being to use the pricing tools to get a much more accurate price than the vision model does. Once I have it "working" we can work on improving and adding to the tools with other web search tools and keepa/scryfall/etc.

Next phase might be to put a "front end" to take the pictures instead of using an iOS shortcut. I'd also like to be able to do 3-5 photos in some cases where that makes sense. I also plan on making an eBay listing tool either by expanding this, or at least using a lot of the pricing_tools in that as well.