"""
prompts
-------
Category-driven prompt strategy for the vision step. Each category supplies
its own base prompt; vision.py dispatches via build_prompt(category, batch_notes).

When ENABLE_GENERALIST_MODE is off, callers force category="card" so the
existing card prompt is returned byte-for-byte.
"""

from .card import CARD_PROMPT
from .antique import ANTIQUE_PROMPT


def build_prompt(category: str, batch_notes: str = "") -> str:
    """Return the full prompt for a category, with optional batch context prepended."""
    base = _base_for_category(category)
    notes = (batch_notes or "").strip()
    if not notes:
        return base
    return (
        f"BATCH CONTEXT — applies to every item in this session:\n"
        f"{notes}\n\n"
        f"Use this context to help identify items (e.g. if the batch says "
        f"'Pokemon fan art', treat all items accordingly).\n\n"
        + base
    )


def _base_for_category(category: str) -> str:
    cat = (category or "card").lower()
    if cat == "card":
        return CARD_PROMPT
    return ANTIQUE_PROMPT
