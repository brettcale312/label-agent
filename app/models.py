from pydantic import BaseModel, Field
from typing import List

COMIC_COLUMNS = [
    "Title & Issue",
    "Bullet 1",
    "Bullet 2",
    "Bullet 3",
    "Publisher",
    "Price",
    "Inventory #",
    "Barcode"
]

CARD_COLUMNS = [
    "Title",
    "Bullet 1",
    "Bullet 2",
    "Price Source",
    "Final Price",
    "Inventory #",
    "Barcode"
]

class IngestResponse(BaseModel):
    ok: bool
    added_row: list = Field(default_factory=list)

def row_order(item_type: str) -> List[str]:
    return COMIC_COLUMNS if item_type == "comic" else CARD_COLUMNS
