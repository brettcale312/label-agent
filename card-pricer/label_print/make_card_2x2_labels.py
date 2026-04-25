# make_pokemon_2x_labels.py

# pip install reportlab python-barcode Pillow
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.graphics.barcode import code128
from reportlab.lib.utils import simpleSplit

import csv
import os
import sys
from pathlib import Path

# ---------- CONFIG (defaults) ----------
PAGE_W = 2 * inch     # each label is a 2" x 2" page
PAGE_H = 2 * inch

# Type stack that matched your "reverted_description_labels" look
TITLE_FONT = "Helvetica-Bold"
BODY_FONT  = "Helvetica"   # you wanted bullets bold
TITLE_SIZE = 10                 # this is the "minus 1pt" version you liked
BODY_SIZE  = 9
LINE_GAP   = 3                  # space between bullet lines
TOP_PADDING = 6                 # small top margin to avoid clipping
LEFT_MARGIN = 8
RIGHT_MARGIN = 8

BARCODE_HEIGHT = 0.40 * inch    # shorter barcode so it never overruns
BAR_GAP = 6                     # gap between description and barcode block
TEXT_UNDER_BAR_GAP = 2

# Defaults if no CLI args are provided
DEFAULT_DATA_FILE = "card_label_input.txt"
DEFAULT_OUTPUT = "card_2x2_label.pdf"
# --------------------------------------

def read_rows(path):
    """
    Expect tab- or comma-separated lines:
    Title  Bullet1  Bullet2  PriceSource  FinalPrice  InventoryID  Barcode
    (PriceSource is ignored for the label layout you chose.)
    """
    rows = []
    with open(path, "r", encoding="utf-8-sig") as f:
        # sniff delimiter
        sample = f.read(4096)
        f.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters="\t,")
        reader = csv.reader(f, dialect)
        for raw in reader:
            if not raw or all(not x.strip() for x in raw):
                continue
            # pad in case a column is missing
            while len(raw) < 7:
                raw.append("")
            title, b1, b2, _price_src, final_price, inv_id, barcode_val = [x.strip() for x in raw[:7]]
            rows.append({
                "title": title,
                "b1": b1,
                "b2": b2,
                "price": final_price,
                "inv": inv_id,
                "barcode": barcode_val
            })
    return rows

def wrap_text(text, fontName, fontSize, max_width):
    return simpleSplit(text, fontName, fontSize, max_width)

def draw_label(c, row):
    c.setFillColor(colors.black)
    c.setStrokeColor(colors.black)
    # c.setLineWidth(0.5); c.rect(1, 1, PAGE_W-2, PAGE_H-2)  # debug border if needed

    # DESCRIPTION (top)
    x = LEFT_MARGIN
    usable_w = PAGE_W - LEFT_MARGIN - RIGHT_MARGIN
    y = PAGE_H - TOP_PADDING

    # Title
    c.setFont(TITLE_FONT, TITLE_SIZE)
    title_lines = wrap_text(row["title"], TITLE_FONT, TITLE_SIZE, usable_w)
    for i, line in enumerate(title_lines):
        y -= TITLE_SIZE if i == 0 else (TITLE_SIZE + 1)
        c.drawString(x, y, line)

    # Bullets
    c.setFont(BODY_FONT, BODY_SIZE)
    def bullet(line): return f"• {line}"
    bullets = [
        bullet(row["b1"]),
        bullet(row["b2"]),
        bullet(f"Price: {row['price']} | ID: {row['inv']}")
    ]
    for text in bullets:
        lines = wrap_text(text, BODY_FONT, BODY_SIZE, usable_w)
        for i, line in enumerate(lines):
            y -= (BODY_SIZE + (LINE_GAP if i == len(lines)-1 else 1))
            c.drawString(x, y, line)

    #y -= BODY_SIZE + LINE_GAP

    # c.setFont(BODY_FONT, BODY_SIZE)
    # num_text = row["barcode"]
    # c.drawCentredString(PAGE_W/2.0, y, num_text)
    y -= BAR_GAP  # slightly reduced gap before barcode itself

    # BARCODE (bottom)
    bc = code128.Code128(row["barcode"], barHeight=BARCODE_HEIGHT, barWidth=0.0125*inch, humanReadable=False)
    bc_w = bc.width
    bc_x = (PAGE_W - bc_w) / 2
    bc_y = max(8, y - BARCODE_HEIGHT)  # keep above bottom edge
    bc.drawOn(c, bc_x, bc_y)

    # Text under the barcode (ID and price), centered
    # footer_text = f"{row['inv']}    {row['price']}"
    footer_text = f"{row['barcode']}"
    c.setFont(TITLE_FONT, BODY_SIZE)
    c.drawCentredString(PAGE_W / 2, bc_y - TEXT_UNDER_BAR_GAP - BODY_SIZE, footer_text)

def main():
    # If args provided: use them. Else: fall back to defaults next to the script.
    if len(sys.argv) >= 3:
        data_file = Path(sys.argv[1])
        output_pdf = Path(sys.argv[2])
    else:
        here = Path(__file__).resolve().parent
        data_file = here / DEFAULT_DATA_FILE
        output_pdf = here / DEFAULT_OUTPUT
        print(f"[info] No args provided. Using defaults:\n  input={data_file}\n  output={output_pdf}")

    if not data_file.exists():
        raise SystemExit(f"[error] Input file not found: {data_file}")

    rows = read_rows(str(data_file))
    if not rows:
        raise SystemExit("[error] No rows parsed. Check your separators (tab or comma).")

    # Ensure output directory exists
    output_pdf.parent.mkdir(parents=True, exist_ok=True)

    c = canvas.Canvas(str(output_pdf), pagesize=(PAGE_W, PAGE_H))
    for row in rows:
        draw_label(c, row)
        c.showPage()
    c.save()
    print(f"Done: {output_pdf} ({len(rows)} labels)")

if __name__ == "__main__":
    main()
