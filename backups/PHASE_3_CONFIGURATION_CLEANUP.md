# Phase 3: Configuration & Cleanup Plan

## Overview

**Goal**: Extract configuration constants, implement automatic temp file cleanup, and create comprehensive environment documentation.

**Status**: Ready to execute after Phase 2 completion  
**Dependencies**: Phase 2 pricing integration must be complete and tested

---

## Implementation Tasks

### Task 1: Extract Price Constants

**File**: `app/config.py`  
**Current**: Basic environment loading  
**Add**: Price floor constants

```python
# Price floor constants for different item types
PRICE_FLOORS = {
    "comic": 4.00,
    "record": 4.00,
    "card": 1.00,
    "anything": 3.00,
    "item": 3.00,
}

# Price rounding rules
ROUNDING_RULES = {
    "above_5_dollars": "round_up_to_nearest_dollar",
    "below_5_dollars": "round_up_to_nearest_fifty_cents",
}
```

**Files to Update**:
- `app/pricing.py` - Reference `config.PRICE_FLOORS` instead of hardcoded values
- `app/vision.py` - Reference `config.PRICE_FLOORS` instead of hardcoded values

### Task 2: Create .env.example

**File**: `.env.example` (new file)  
**Purpose**: Document all required environment variables for new developers

```env
# API Keys
OPENAI_API_KEY=sk-your-openai-key-here
DISCOGS_TOKEN=your-discogs-token-here
BRAVE_API_KEY=your-brave-api-key-here
EBAY_APP_ID=your-ebay-app-id
EBAY_CERT_ID=your-ebay-cert-id
EBAY_REFRESH_TOKEN=your-ebay-refresh-token

# Sandpiper Integration
SANDPIPER_USERNAME=your-sandpiper-username
SANDPIPER_PASSWORD=your-sandpiper-password
SANDPIPER_ACCOUNT_ID=your-sandpiper-account-id
SANDPIPER_BOOTH=your-sandpiper-booth-number

# Google Sheets Integration
APPS_SCRIPT_WEBHOOK=https://script.google.com/macros/s/YOUR_SCRIPT_ID/exec

# Server Configuration
LOCAL_IP=10.0.0.66

# iOS Shortcuts (optional)
CARD_SHORTCUT=Scan Card For Label
COMIC_SHORTCUT=Scan Comic For Label
RECORD_SHORTCUT=Scan Record For Label
ANYTHING_SHORTCUT=Scan Anything For Label

# Feature Flags
DEBUG_LOGS=false
ENV=dev

# Future APIs (optional)
KEEPA_API_KEY=your-keepa-api-key
SCRYFALL_API_KEY=your-scryfall-api-key
```

### Task 3: Implement Temp File Cleanup

**File**: `app/main.py`  
**Location**: `/approve` endpoint  
**Add**: Automatic cleanup after successful approval

```python
# After successful approval and Sheets append
try:
    os.remove(path)  # Remove temp_{session_id}.json
    logger.info(f"Cleaned up temp file: {path}")
except Exception as e:
    logger.warning(f"Failed to clean up temp file {path}: {e}")
```

**Add Startup Cleanup**:
```python
def cleanup_old_temp_files():
    """Remove temp JSON files older than 24 hours"""
    import time
    import glob
    cutoff = time.time() - 86400  # 24 hours
    for file in glob.glob("logs/temp_*.json"):
        if os.path.getmtime(file) < cutoff:
            try:
                os.remove(file)
                logger.info(f"Cleaned up old temp file: {file}")
            except Exception as e:
                logger.warning(f"Failed to clean up old temp file {file}: {e}")

# Call during app startup
cleanup_old_temp_files()
```

### Task 4: Update Documentation

**File**: `README.md`  
**Updates**:
- Document pricing model integration
- List all available pricing sources
- Mark Keepa and Scryfall as "available but not yet integrated"
- Update architecture description
- Add troubleshooting section

**New Sections**:
```markdown
## Pricing Sources

### Active Sources
- **eBay Browse API**: Active listings, median pricing
- **Discogs**: Music media, authoritative for records
- **Brave Search**: Web search fallback

### Available Sources (Not Yet Integrated)
- **Keepa**: Amazon product pricing
- **Scryfall**: Magic: The Gathering card pricing
- **DuckDuckGo**: Alternative web search

## Troubleshooting

### Common Issues
1. **Server not accessible from phone**: Use `--host 0.0.0.0`
2. **uvicorn not found**: Use `.\.venv\Scripts\uvicorn.exe`
3. **Apps Script errors**: Check Google Sheet column headers
4. **Pricing API failures**: Check API keys and rate limits
```

---

## Implementation Steps

### Step 1: Extract Constants
1. Add price floor constants to `app/config.py`
2. Update `app/pricing.py` to use constants
3. Update `app/vision.py` to use constants
4. Test that pricing rules still work correctly

### Step 2: Create Environment Template
1. Create `.env.example` file
2. Document all required variables
3. Add helpful comments
4. Test with new developer setup

### Step 3: Implement Cleanup
1. Add temp file cleanup to `/approve` endpoint
2. Add startup cleanup function
3. Test cleanup functionality
4. Verify no temp files accumulate

### Step 4: Update Documentation
1. Update README.md with new information
2. Add troubleshooting section
3. Document pricing sources
4. Update architecture description

---

## Testing Checklist

### Configuration Testing
- [ ] Price floors work correctly for all item types
- [ ] Constants are properly imported
- [ ] No hardcoded values remain

### Environment Testing
- [ ] `.env.example` contains all required variables
- [ ] New developer can set up environment
- [ ] All API keys documented

### Cleanup Testing
- [ ] Temp files removed after approval
- [ ] Old temp files cleaned up on startup
- [ ] No temp files accumulate over time
- [ ] Cleanup errors handled gracefully

### Documentation Testing
- [ ] README.md is up to date
- [ ] Troubleshooting section helpful
- [ ] Architecture description accurate
- [ ] Pricing sources documented

---

## Expected Outcomes

### Code Quality
- **Maintainability**: Constants centralized, easy to modify
- **Documentation**: Clear setup instructions for new developers
- **Cleanliness**: No temp file accumulation
- **Reliability**: Better error handling

### Developer Experience
- **Onboarding**: Faster setup with `.env.example`
- **Debugging**: Better troubleshooting documentation
- **Maintenance**: Easier to modify price floors
- **Monitoring**: Cleaner logs directory

---

## Risk Mitigation

### Configuration Changes
- **Backup**: Test constants with existing data
- **Validation**: Ensure all item types still work
- **Rollback**: Keep old hardcoded values as comments

### Cleanup Implementation
- **Safety**: Only remove files older than 24 hours
- **Error handling**: Log cleanup failures, don't crash
- **Testing**: Verify cleanup doesn't remove active sessions

### Documentation Updates
- **Accuracy**: Test all documented procedures
- **Completeness**: Ensure all features documented
- **Clarity**: Use clear, step-by-step instructions

---

## Success Metrics

### Quantitative
- **Temp files**: 0 accumulation over 24+ hours
- **Setup time**: <10 minutes for new developer
- **Constants**: 100% hardcoded values eliminated
- **Documentation**: 100% features documented

### Qualitative
- **Maintainability**: Easier to modify price floors
- **Onboarding**: Faster new developer setup
- **Reliability**: Cleaner system operation
- **Support**: Better troubleshooting resources

---

## Implementation Timeline

### Day 1: Configuration Extraction
- Extract price constants
- Update all references
- Test pricing rules

### Day 2: Environment & Cleanup
- Create `.env.example`
- Implement temp file cleanup
- Test cleanup functionality

### Day 3: Documentation
- Update README.md
- Add troubleshooting section
- Final testing and validation

---

## Dependencies

### Required
- Phase 2 pricing integration complete
- All existing functionality working
- Test environment available

### Optional
- New developer for testing setup process
- Production environment for cleanup testing

---

## Rollback Plan

If issues arise:

1. **Revert config changes**: Restore hardcoded values
2. **Disable cleanup**: Comment out cleanup code
3. **Restore documentation**: Revert README changes
4. **Debug issues**: Fix problems offline
5. **Re-implement**: Apply fixes and re-deploy

---

## Future Considerations

### Phase 4: Advanced Features
- **Configuration UI**: Web interface for price floors
- **Advanced cleanup**: Configurable retention periods
- **Monitoring**: Temp file usage analytics
- **Automation**: Scheduled cleanup tasks

### Long-term
- **Database**: Replace temp files with database
- **Caching**: Implement result caching
- **Analytics**: Usage and performance metrics
- **Scaling**: Multi-instance deployment support

---

## Ready to Execute

**Status**: Ready after Phase 2 completion  
**Dependencies**: Pricing integration must be stable  
**Testing**: Comprehensive test plan available  
**Next Command**: "Execute Phase 3"
