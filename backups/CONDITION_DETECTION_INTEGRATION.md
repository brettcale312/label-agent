# Condition Detection Integration

## Overview

This document describes the integration of condition detection into the label agent's vision and pricing system. The system now automatically detects the physical condition of scanned items (records, comics, cards) and applies appropriate condition-based pricing adjustments using human-accurate valuation logic.

## Architecture

### Data Flow
1. **Image Scan** → Vision Model analyzes image for item details AND condition
2. **Condition Detection** → AI identifies physical condition based on visual cues
3. **Pricing Integration** → Condition data passed to human-accurate valuation logic
4. **Condition Multipliers** → Appropriate pricing adjustments applied based on condition

## Implementation Details

### 1. Data Model Updates (`app/models.py`)

Added "Condition" field to all collectible item types:

```python
COMIC_COLUMNS = [
    "Title & Issue",
    "Bullet 1", 
    "Bullet 2",
    "Bullet 3",
    "Publisher",
    "Condition",    # ← Added
    "Price",
    "Inventory #",
    "Barcode"
]

CARD_COLUMNS = [
    "Title",
    "Bullet 1",
    "Bullet 2", 
    "Price Source",
    "Condition",    # ← Added
    "Price",
    "Inventory #",
    "Barcode"
]

RECORD_COLUMNS = [
    "Title",
    "Artist",
    "Label",
    "Year", 
    "Genre",
    "Condition",    # ← Added
    "Price",
    "Inventory #",
    "Barcode"
]
```

### 2. Vision Model Updates (`app/vision.py`)

#### Record Condition Detection
```python
context = """
Condition: Assess the record's physical condition based on visible cues:
  - "sealed": Still in original shrink wrap
  - "mint": Near perfect, no visible wear
  - "vg+": Very good plus, minimal wear
  - "vg": Very good, some wear but plays well
  - "good": Good condition, noticeable wear but functional
  - "fair": Fair condition, significant wear but playable
"""
```

#### Comic Condition Detection
```python
context = """
Condition: Assess the comic's physical condition based on visible cues:
  - "mint": Near perfect, no visible wear or damage
  - "near mint": Excellent condition, minimal handling wear
  - "very fine": Very good condition, slight wear
  - "fine": Good condition, some wear but well-preserved
  - "very good": Noticeable wear but still collectible
  - "good": Fair condition, significant wear but intact
"""
```

#### Card Condition Detection
```python
context = """
Condition: Assess the card's physical condition based on visible cues:
  - "mint": Near perfect, no visible wear or damage
  - "near mint": Excellent condition, minimal handling wear
  - "lightly played": Very good condition, slight wear
  - "moderately played": Good condition, some wear but well-preserved
  - "heavily played": Noticeable wear but still playable
  - "damaged": Significant wear, creases, or damage
"""
```

#### Pricing Integration Update
```python
# Extract condition from vision model output
condition = ordered.get("Condition") or "vg"

# Pass condition to pricing system
price_result = get_best_price(
    title=title, 
    artist=artist, 
    category=type_, 
    condition=condition,  # ← Now uses detected condition
    venue="antique_store"
)
```

### 3. Valuation Logic Updates (`pricing_tools/valuation_logic.py`)

Enhanced condition multiplier function to handle all item types:

```python
def apply_condition_multiplier(base: float, condition: str) -> float:
    condition = (condition or "").lower()
    
    # Record conditions
    if "sealed" in condition:
        return base * 1.6
    if "mint" in condition:
        return base * 1.6
    if "vg+" in condition:
        return base * 1.2
    if "vg" in condition:
        return base * 1.0
    if "good" in condition:
        return base * 0.7
    if "fair" in condition:
        return base * 0.5
    
    # Comic conditions
    if "near mint" in condition:
        return base * 1.4
    if "very fine" in condition:
        return base * 1.2
    if "fine" in condition:
        return base * 1.0
    if "very good" in condition:
        return base * 0.8
    
    # Card conditions
    if "lightly played" in condition:
        return base * 1.2
    if "moderately played" in condition:
        return base * 1.0
    if "heavily played" in condition:
        return base * 0.7
    if "damaged" in condition:
        return base * 0.5
    
    # Default fallback
    return base * 1.0
```

## Condition Multipliers

### Records
| Condition | Multiplier | Example ($10 base) |
|-----------|------------|-------------------|
| Sealed | 1.6x | $16.00 |
| Mint | 1.6x | $16.00 |
| VG+ | 1.2x | $12.00 |
| VG | 1.0x | $10.00 |
| Good | 0.7x | $7.00 |
| Fair | 0.5x | $5.00 |

### Comics
| Condition | Multiplier | Example ($10 base) |
|-----------|------------|-------------------|
| Mint | 1.6x | $16.00 |
| Near Mint | 1.6x | $16.00 |
| Very Fine | 1.2x | $12.00 |
| Fine | 1.0x | $10.00 |
| Very Good | 0.8x | $8.00 |
| Good | 0.7x | $7.00 |

### Cards
| Condition | Multiplier | Example ($10 base) |
|-----------|------------|-------------------|
| Mint | 1.6x | $16.00 |
| Near Mint | 1.6x | $16.00 |
| Lightly Played | 1.2x | $12.00 |
| Moderately Played | 1.0x | $10.00 |
| Heavily Played | 0.7x | $7.00 |
| Damaged | 0.5x | $5.00 |

## Benefits

1. **Accurate Pricing**: Condition-based adjustments ensure pricing reflects actual item value
2. **Automatic Detection**: No manual condition input required - AI analyzes visual cues
3. **Consistent Standards**: Standardized condition grades across all item types
4. **Human-Accurate Logic**: Pricing matches real-world antique store valuations
5. **Scalable**: Easy to add new condition grades or adjust multipliers

## Integration with Human-Accurate Valuation

The condition detection integrates seamlessly with the existing human-accurate valuation logic:

1. **Vision Model** detects condition from scanned image
2. **Valuation Logic** applies condition multipliers to base market prices
3. **Venue Adjustments** apply antique store retail markup
4. **Final Pricing** reflects realistic market values based on actual condition

## Example Workflow

1. **Scan**: User scans a Chicago Transit Authority record
2. **Vision Analysis**: AI detects "Title: Chicago Transit Authority", "Artist: Chicago", "Condition: sealed"
3. **Market Data**: System fetches Discogs median ($1.62) and eBay median ($17.49)
4. **Valuation**: 
   - Base price: $17.49 (eBay median)
   - Condition: +60% (sealed) = $27.98
   - Venue: +40% (antique store) = $39.17
   - Final: $39.95 (rounded to retail pricing)
5. **Result**: Accurate pricing that reflects both market value and physical condition

## Future Enhancements

- Add condition detection for "anything" category items
- Implement condition-based search query optimization for better market data
- Add condition confidence scoring for edge cases
- Support for custom condition grades per item type
