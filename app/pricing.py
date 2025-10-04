import re

async def apply_pricing_rules(type_: str, fields: dict) -> dict:
    """
    Apply pricing rules for comics and cards.
    Ensures prices are strings like "$4.00" or "$1.00".
    """

    key = "Price" if type_ == "comic" else "Final Price"
    val = fields.get(key, "")

    # Debug (optional):
    # print(f"[DEBUG][pricing] initial {key}: {repr(val)}")

    # If it's already a properly formatted currency string, leave it alone
    if isinstance(val, str) and val.strip().startswith("$"):
        # Debug (optional):
        # print(f"[DEBUG][pricing] already formatted: {val}")
        return fields

    # Try to extract a numeric value from whatever we got
    num = None
    if isinstance(val, (int, float)):
        num = float(val)
    elif isinstance(val, str):
        match = re.search(r"(\d+(\.\d+)?)", val)
        if match:
            num = float(match.group(1))

    # Debug (optional):
    # print(f"[DEBUG][pricing] parsed numeric: {num}")

    if num is not None:
        # Apply floors
        if type_ == "comic" and num < 4.0:
            num = 4.0
        if type_ == "card" and num < 1.0:
            num = 1.0

        # Rounding rules
        if num > 5:
            num = int(num) if num == int(num) else int(num) + 1
        else:
            num = round(num * 2) / 2.0

        fields[key] = f"${num:.2f}"
        # Debug (optional):
        # print(f"[DEBUG][pricing] final {key}: {fields[key]}")
    else:
        # If no price could be parsed, enforce minimums
        fields[key] = "$4.00" if type_ == "comic" else "$1.00"
        # Debug (optional):
        # print(f"[DEBUG][pricing] enforced minimum: {fields[key]}")

    return fields
