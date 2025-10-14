import re

async def apply_pricing_rules(type_: str, fields: dict) -> dict:
    """
    Apply pricing rules for comics, cards, records, and misc items.
    Ensures all use the unified 'Price' field formatted as '$X.XX'.
    """

    key = "Price"
    val = fields.get(key, "")

    # If it's already a properly formatted currency string, leave it alone
    if isinstance(val, str) and val.strip().startswith("$"):
        return fields

    # Try to extract a numeric value from whatever we got
    num = None
    if isinstance(val, (int, float)):
        num = float(val)
    elif isinstance(val, str):
        match = re.search(r"(\d+(\.\d+)?)", val)
        if match:
            num = float(match.group(1))

    if num is not None:
        # Apply category-based floors
        if type_ in ("comic", "record") and num < 4.0:
            num = 4.0
        elif type_ == "card" and num < 1.0:
            num = 1.0
        elif type_ in ("item", "anything") and num < 3.0:
            num = 3.0

        # Rounding rules
        if num > 5:
            num = int(num) if num == int(num) else int(num) + 1
        else:
            num = round(num * 2) / 2.0

        fields[key] = f"${num:.2f}"
    else:
        # Enforce minimum if no valid number found
        if type_ in ("comic", "record"):
            fields[key] = "$4.00"
        elif type_ == "card":
            fields[key] = "$1.00"
        else:
            fields[key] = "$3.00"

    return fields
