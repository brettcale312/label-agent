# Phase 2: Pricing Integration Plan

## Overview

**Goal**: Integrate `pricing_tools/pricing_model.py` into the vision workflow to replace AI-estimated pricing with accurate market data from eBay, Discogs, and Brave Search.

**Current Problem**: The vision model in `app/vision.py` generates inaccurate prices because it lacks web search capabilities.

**Solution**: After OpenAI Vision identifies an item, call the pricing model to get real market data instead of relying on AI estimates.

---

## Technical Implementation

### Integration Point

**File**: `app/vision.py`  
**Location**: Lines 215-242 (price enforcement section)  
**Current Code**:
```python
# Vision estimates price directly
ordered["Price"] = enforce_price(ordered.get("Price", ""), "$4.00")
```

**New Code**:
```python
# Get real market pricing after vision extracts title/artist
from pricing_tools.pricing_model import get_best_price

# Extract base identification first
title = ordered.get("Title") or ordered.get("Title & Issue")
artist = ordered.get("Artist") if type_ == "record" else None

# Get market price (async-safe)
import asyncio
price_result = get_best_price(title, artist=artist, category=type_)

# Use market price if available, otherwise fall back to vision estimate
if price_result.get("final_price"):
    ordered["Price"] = f"${price_result['final_price']:.2f}"
    # Optionally log sources for debugging
    if DEBUG_LOGS:
        logger.info(f"Market price sources: {price_result.get('sources', {})}")
else:
    # Fallback to vision estimate
    ordered["Price"] = enforce_price(ordered.get("Price", ""), minimum_price)
```

### Pricing Model Logic

The `pricing_model.py` uses this priority system:

1. **Discogs** (for records/media) - If found, use exclusively
2. **eBay + Brave Search** (weighted average) - If no Discogs result
   - eBay: 75% weight
   - Brave Search: 25% weight
3. **Fallback** - If no market data found, use vision estimate

### Price Enforcement Integration

**File**: `app/pricing.py`  
**Function**: `apply_pricing_rules()`  
**Status**: No changes needed - already handles market prices correctly

The existing price enforcement will:
1. Apply category-based floors to market prices
2. Apply rounding rules (same as current)
3. Work seamlessly with both market prices and vision estimates

---

## Implementation Steps

### Step 1: Import Integration
- Add import for `get_best_price` function
- Add import for `asyncio` (if not already present)
- Add logger import for debug output

### Step 2: Extract Item Identification
- Get title from appropriate field based on item type
- Get artist for records
- Prepare category parameter

### Step 3: Call Pricing Model
- Call `get_best_price()` with extracted parameters
- Handle async execution safely
- Check for valid results

### Step 4: Apply Market Price
- Use market price if available
- Format as currency string
- Log sources for debugging
- Fall back to vision estimate if no market data

### Step 5: Test All Item Types
- Test with records (should use Discogs)
- Test with comics (should use eBay + Brave)
- Test with cards (should use eBay + Brave)
- Test with obscure items (should fall back gracefully)

---

## Expected Outcomes

### Before Integration
- **Vision estimates**: Often inaccurate, no market data
- **Price sources**: AI-only, unreliable
- **Accuracy**: Poor for market pricing

### After Integration
- **Market pricing**: Real data from eBay, Discogs, Brave Search
- **Price sources**: Multiple APIs with intelligent weighting
- **Accuracy**: Significantly improved market-based pricing
- **Fallback**: Graceful degradation to vision estimates

### Debug Output
With `DEBUG_LOGS=true`, you'll see:
```
[DEBUG] Apps Script returned: '718-5513' for type 'card'
[INFO] Market price sources: {'eBay': 12.50, 'WebSearch': 15.00}
[INFO] Final weighted price: $13.13
```

---

## Testing Strategy

### Test Cases

1. **Record with Discogs match**
   - Input: "Abbey Road" by The Beatles
   - Expected: Discogs price used exclusively
   - Verify: No eBay/Brave calls made

2. **Comic with eBay data**
   - Input: "Action Comics #1061"
   - Expected: eBay + Brave weighted average
   - Verify: Both APIs called, proper weighting applied

3. **Card with mixed results**
   - Input: "Pokémon Pikachu EX"
   - Expected: eBay + Brave weighted average
   - Verify: Fallback if APIs fail

4. **Obscure item**
   - Input: "Custom handmade item"
   - Expected: Fallback to vision estimate
   - Verify: Graceful degradation

### Validation

- **Price accuracy**: Compare to manual eBay/Discogs searches
- **Response time**: Should be <5 seconds total
- **Error handling**: APIs should fail gracefully
- **Logging**: Debug output should show sources

---

## Risk Mitigation

### API Failures
- **eBay API down**: Fall back to Brave Search only
- **Discogs API down**: Use eBay + Brave weighted average
- **All APIs down**: Fall back to vision estimate
- **Timeout handling**: 10-second timeout per API call

### Data Quality
- **Invalid prices**: Filter out $0 or negative prices
- **Outliers**: Use median instead of average for eBay
- **Missing data**: Graceful fallback to next source

### Performance
- **Async execution**: All API calls run concurrently
- **Caching**: Consider adding result caching later
- **Rate limiting**: Respect API rate limits

---

## Success Metrics

### Quantitative
- **Price accuracy**: 80%+ within 20% of manual market research
- **Response time**: <5 seconds for pricing lookup
- **API success rate**: 90%+ for primary sources
- **Fallback rate**: <10% to vision estimates

### Qualitative
- **User satisfaction**: More accurate pricing
- **Reduced manual correction**: Less editing needed in review
- **Confidence**: Users trust the system more

---

## Rollback Plan

If integration causes issues:

1. **Revert vision.py changes**
2. **Disable pricing model calls**
3. **Return to vision-only pricing**
4. **Debug issues offline**
5. **Re-integrate with fixes**

---

## Future Enhancements

### Phase 3 Considerations
- **Keepa integration**: For general retail items
- **Scryfall integration**: For MTG cards specifically
- **Confidence scoring**: Based on number of sources
- **Caching**: Store results to reduce API calls
- **LangChain integration**: Intelligent tool selection

### Advanced Features
- **Price trends**: Track price changes over time
- **Condition factors**: Adjust prices based on item condition
- **Market analysis**: Provide pricing insights
- **Competitive analysis**: Compare to other sellers

---

## Dependencies

### Required APIs
- **eBay**: Browse API access (already configured)
- **Discogs**: Personal access token (already configured)
- **Brave Search**: API key (already configured)

### Optional APIs (Future)
- **Keepa**: Amazon pricing data
- **Scryfall**: MTG card pricing
- **DuckDuckGo**: Alternative web search

---

## Implementation Timeline

### Day 1: Core Integration
- Implement basic pricing model integration
- Test with simple cases
- Verify fallback behavior

### Day 2: Testing & Refinement
- Test all item types
- Validate price accuracy
- Optimize error handling

### Day 3: Production Ready
- Final testing
- Performance optimization
- Documentation updates

---

## Code Changes Summary

### Files Modified
- `app/vision.py` - Add pricing model integration
- `app/config.py` - Add price floor constants (if needed)

### Files Unchanged
- `app/pricing.py` - Already handles market prices correctly
- `pricing_tools/pricing_model.py` - No changes needed
- `app/main.py` - No changes needed

### New Dependencies
- None (all required modules already imported)

---

## Ready to Execute

**Status**: Ready to implement  
**Dependencies**: All APIs configured and working  
**Testing**: Phase 1 complete and stable  
**Next Command**: "Execute Phase 2"
