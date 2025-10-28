"""
format_rules.py
----------------
Centralized formatting and naming rules for the Pricing Agent.

Builds consistent display and search strings for each collectible type.

Used by:
- review.html (Title column)
- Search queries for pricing tools
- Label printing systems

All types now support 3 bullets and standardized "Base Price" / "Price Source"
fields from the unified schema.
"""

def build_display_and_search_strings(item: dict) -> dict:
    item_type = (item.get("type") or "").lower()

    # -----------------------------------------------------------------
    # COMICS
    # -----------------------------------------------------------------
    if item_type == "comic":
        title = item.get("title") or ""
        issue = item.get("issue_number") or ""
        variant = item.get("variant") or ""
        publisher = item.get("publisher") or ""
        condition = item.get("condition") or ""
        special = []

        # Normalize variant so we can skip "N/A", "None", etc.
        variant_clean = (variant or "").strip().lower()
        if variant_clean in ("", "n/a", "na", "none", "null", "unknown"):
            variant = ""

        # Optional extra tags (signed, key issue, limited, etc.)
        if item.get("autographed"):
            special.append("Signed")
        if item.get("key_issue_details"):
            special.append(item["key_issue_details"])
        if item.get("rarity_or_limited_info"):
            special.append(item["rarity_or_limited_info"])

        # --- Display (for labels & Sheets)
        display = title
        if issue:
            display += f" #{issue}"
        if variant:
            display += f" ({variant})"
        if special:
            display += " – " + ", ".join(special)

        # --- Search (for pricing tools)
        search = " ".join(filter(None, [
            title,
            issue,
            variant,
            publisher,
            condition,
            *special,
            "comic"
        ]))

        item["display_string"] = display.strip()
        item["search_string"] = search.strip()
        return item

    # -----------------------------------------------------------------
    # TRADING CARDS (Pokémon, MTG, Sports, etc.)
    # -----------------------------------------------------------------
    elif item_type == "card":
        subtype = item.get("subtype") or ""     # e.g. Pokémon, MTG, Sports
        title = item.get("title") or ""
        card_num = item.get("card_number") or ""
        rarity = item.get("rarity") or ""
        set_name = item.get("set_name") or ""
        condition = item.get("condition") or ""
        holo = item.get("holo_type") or ""

        # Normalize rarity & skip common ones in display
        rarity_clean = (rarity or "").strip().lower()
        if rarity_clean in ("common", "uncommon", "base", "regular", "none"):
            rarity = ""

        # --- Display (short for 2x2 labels)
        # Example: "Pokémon – Pikachu 25/108 (Holo Rare)"
        display_parts = []
        if subtype:
            display_parts.append(subtype)
        if title:
            if card_num:
                display_parts.append(f"– {title} {card_num}")
            else:
                display_parts.append(f"– {title}")
        if rarity or holo:
            display_parts.append(f"({rarity or holo})")
        display = " ".join(display_parts).strip()

        # --- Search (expanded for pricing lookups)
        search = " ".join(filter(None, [
            subtype,
            title,
            card_num,
            rarity,
            holo,
            set_name,
            condition,
            "card"
        ]))

        item["display_string"] = display.strip()
        item["search_string"] = search.strip()
        return item

    # -----------------------------------------------------------------
    # VINYL RECORDS
    # -----------------------------------------------------------------
    elif item_type == "record":
        title = item.get("title") or ""
        artist = item.get("artist") or ""
        year = item.get("year") or ""
        label = item.get("publisher") or ""
        genre = item.get("genre") or ""

        # --- Display (clean, record-store style)
        # Example: "Fleetwood Mac – Rumours (1977)"
        display = f"{artist} – {title}".strip()
        if year:
            display += f" ({year})"

        # --- Search (expanded for tool queries)
        search = " ".join(filter(None, [
            artist,
            title,
            label,
            genre,
            year,
            "vinyl",
            "record"
        ]))

        item["display_string"] = display.strip()
        item["search_string"] = search.strip()
        return item

    # -----------------------------------------------------------------
    # ANYTHING / MISC
    # -----------------------------------------------------------------
    else:
        title = item.get("title") or "Untitled Item"
        category = item.get("category_hint") or "misc"
        condition = item.get("condition") or ""

        # --- Display
        display = title

        # --- Search
        search = " ".join(filter(None, [title, category, condition]))

        item["display_string"] = display.strip()
        item["search_string"] = search.strip()
        return item
