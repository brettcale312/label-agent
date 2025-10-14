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
    "Price",
    "Inventory #",
    "Barcode"
]

ANYTHING_COLUMNS = [
    "Title",
    "Category",
    "Description",
    "Price",
    "Inventory #",
    "Barcode",
    "AI Notes"
]


class IngestResponse(BaseModel):
    ok: bool
    added_row: list = Field(default_factory=list)

from typing import List

def row_order(item_type: str) -> List[str]:
    item_type = (item_type or "").lower()

    if item_type == "comic":
        return COMIC_COLUMNS
    elif item_type == "card":
        return CARD_COLUMNS
    elif item_type == "record":
        return RECORD_COLUMNS
    else:  # anything / misc
        return ANYTHING_COLUMNS
