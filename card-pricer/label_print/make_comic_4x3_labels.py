
# make_rollo_4x3_labels.py
# Generate 4x3 inch portrait labels with barcode (Code 128) for a Rollo printer.
# Usage:
#   1) Install Python 3.9+
#   2) pip install reportlab
#   3) python make_rollo_4x3_labels.py input.tsv output.pdf
#
# The TSV must have 8 columns in this order:
# Title, Bullet1, Bullet2, Bullet3, Publisher, Price, InventoryID, BarcodeNumber

import csv
import sys
import unicodedata
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.graphics.barcode import code128
from reportlab.lib.colors import black, gray
from pathlib import Path

PAGE_W, PAGE_H = 4 * inch, 3 * inch
MARGIN = 0.25 * inch
MAX_TEXT_W = PAGE_W - 2 * MARGIN

# Basic Helvetica works, but we normalize dashes to hyphen-minus to avoid missing glyph squares

def normalize_text(s: str) -> str:
    if not s:
        return ""
    # Hyphen/space normalizations
    s = s.replace("‑", "-")  # non-breaking hyphen → regular hyphen
    s = s.replace("–", "-")  # en dash
    s = s.replace("—", "-")  # em dash
    s = s.replace(" ", " ")  # non-breaking space
    s = s.replace("‐", "-")       # hyphen character (U+2010)
    return s


def wrap_text(canvas_obj, text, x, y, width, leading, font_name="Helvetica", font_size=11):
    """Draws wrapped text (left aligned). Returns the new y after drawing."""
    words = text.split()
    line = ""
    for w in words:
        test = (line + " " + w).strip()
        if canvas_obj.stringWidth(test, font_name, font_size) <= width:
            line = test
        else:
            canvas_obj.setFont(font_name, font_size)
            canvas_obj.drawString(x, y, line)
            y -= leading
            line = w
    if line:
        canvas_obj.setFont(font_name, font_size)
        canvas_obj.drawString(x, y, line)
        y -= leading
    return y

def draw_label(c, row):
    title, b1, b2, b3, publisher, price, inv_id, barcode_num = [normalize_text(col) for col in row]
    price_display = price.strip()
    # Start at top-left
    x = MARGIN
    y = PAGE_H - MARGIN

    # Title (bold) – allow wrap
    c.setFont("Helvetica-Bold", 12)
    y = wrap_text(c, title, x, y, MAX_TEXT_W, leading=13, font_name="Helvetica-Bold", font_size=12) + 2
    y -= 3

    # Bullets
    c.setFont("Helvetica", 11)
    bullets = [b for b in [b1, b2, b3] if b and b.strip()]
    for b in bullets:
        line = f"• {b.strip()}"
        y = wrap_text(c, line, x, y, MAX_TEXT_W, leading=11, font_name="Helvetica", font_size=11)
        y -= 3

    # Publisher (italic)
    if publisher.strip():
        y = wrap_text(c, f"• Publisher: {publisher.strip()}", x, y, MAX_TEXT_W, leading=11, font_name="Helvetica-Oblique", font_size=11)
        y -= 3

    # Price (bold label and amount)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(x, y, "• Price: ")
    price_x = x + c.stringWidth("• Price: ", "Helvetica-Bold", 12)
    c.drawString(price_x, y, price_display)
    y -= 15

    # Inventory ID (bold label + value bold)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(x, y, "Inventory ID: " + inv_id)
    y -= 12

    # Space then barcode number (centered)
    y -= 6  # tighten spacing before the barcode number
    c.setFont("Helvetica", 9)
    num_text = barcode_num
    c.drawCentredString(PAGE_W/2.0, y, num_text)
    y -= 6  # slightly reduced gap before barcode itself

    # Barcode (Code128), centered and scaled to target width
    target_w = 2.6*inch
    bc = code128.Code128(barcode_num, barHeight=0.30*inch, humanReadable=False)
    scale = min(target_w / bc.width, 1.8)  # safety cap on scale
    bc_x = (PAGE_W - bc.width*scale)/2.0
    bc_y = y - bc.height*scale
    c.saveState()
    c.translate(bc_x, bc_y)
    c.scale(scale, scale)
    bc.drawOn(c, 0, 0)
    c.restoreState()

    # Bottom line centered: Inventory + Price
    c.setFont("Helvetica-Bold", 10)
    bottom_text = f"{inv_id}   {price_display}"
    c.drawCentredString(PAGE_W/2.0, bc_y - 12, bottom_text)

def main():
    # Default to files next to the script if no args are provided
    if len(sys.argv) < 3:
        here = Path(__file__).resolve().parent
        inp = here / "comic_label_input.txt"
        outp = here / "comic_4x3_label.pdf"
        print(f"[info] No args given. Using defaults:\n  input={inp}\n  output={outp}")
    else:
        inp, outp = Path(sys.argv[1]), Path(sys.argv[2])

    if not inp.exists():
        print(f"[error] Input file not found: {inp}")
        sys.exit(1)

    c = canvas.Canvas(str(outp), pagesize=(PAGE_W, PAGE_H))
    with open(inp, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f, delimiter="\t")
        for row in reader:
            if not row or all(not (cell or "").strip() for cell in row):
                continue
            if len(row) < 8:
                raise ValueError("Each row must have 8 columns (Title, Bullet1, Bullet2, Bullet3, Publisher, Price, Inventory ID, Barcode).")
            draw_label(c, row[:8])
            c.showPage()
    c.save()
    print(f"Saved {outp}")

if __name__ == "__main__":
    main()
