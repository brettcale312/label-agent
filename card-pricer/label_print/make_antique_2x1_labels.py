# make_antique_2x1_labels.py
# 2" x 1" label for antique / general items — title, price, inv ID, barcode.
# No bullets (not enough vertical space). Designed for Rollo thermal printer.
#
# Input TSV columns (4):
#   Title, Price, InventoryID, BarcodeNumber
#
# Usage:
#   python make_antique_2x1_labels.py input.tsv output.pdf

import csv
import sys
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.graphics.barcode import code128

PAGE_W = 2 * inch
PAGE_H = 1 * inch
MARGIN = 0.08 * inch      # tight margins — small label
BARCODE_H = 0.27 * inch   # leave enough room for text above


def _truncate(c_obj, text: str, font: str, size: float, max_w: float) -> str:
    """Trim text with ellipsis until it fits max_w."""
    if not text:
        return ""
    while text and c_obj.stringWidth(text, font, size) > max_w:
        text = text[:-1]
    return text


def normalize(s: str) -> str:
    return (s or "").replace("–", "-").replace("—", "-").replace(" ", " ")


def draw_label(c, title: str, price: str, inv_id: str, barcode_val: str):
    title     = normalize(title)
    price     = normalize(price)
    inv_id    = normalize(inv_id)
    barcode_val = normalize(barcode_val)

    usable_w = PAGE_W - 2 * MARGIN

    # ── Price (top-right, bold) ────────────────────────────────────────────
    price_font, price_size = "Helvetica-Bold", 9
    c.setFont(price_font, price_size)
    price_w = c.stringWidth(price, price_font, price_size)
    price_x = PAGE_W - MARGIN - price_w
    price_y = PAGE_H - MARGIN - price_size
    c.drawString(price_x, price_y, price)

    # ── Title (top-left, bold, truncated to leave room for price) ──────────
    title_font, title_size = "Helvetica-Bold", 9
    title_max_w = usable_w - price_w - 6   # 6pt gap between title and price
    title_display = _truncate(c, title, title_font, title_size, title_max_w)
    c.setFont(title_font, title_size)
    c.drawString(MARGIN, price_y, title_display)

    # ── Inventory ID (second line, smaller) ────────────────────────────────
    inv_font, inv_size = "Helvetica", 7
    c.setFont(inv_font, inv_size)
    inv_y = price_y - inv_size - 2
    c.drawString(MARGIN, inv_y, f"ID: {inv_id}")

    # ── Barcode (bottom, centered) ─────────────────────────────────────────
    if barcode_val:
        bc = code128.Code128(
            barcode_val, barHeight=BARCODE_H, barWidth=0.013 * inch, humanReadable=False
        )
        bc_x = (PAGE_W - bc.width) / 2
        # sit barcode above the number text at bottom
        num_size = 6
        bc_y = MARGIN + num_size + 2
        bc.drawOn(c, bc_x, bc_y)

        # Barcode number beneath barcode
        c.setFont("Helvetica", num_size)
        c.drawCentredString(PAGE_W / 2, MARGIN, barcode_val)


def main():
    if len(sys.argv) >= 3:
        inp  = Path(sys.argv[1])
        outp = Path(sys.argv[2])
    else:
        here = Path(__file__).resolve().parent
        inp  = here / "antique_2x1_input.txt"
        outp = here / "antique_2x1_label.pdf"
        print(f"[info] No args — using defaults:\n  input={inp}\n  output={outp}")

    if not inp.exists():
        raise SystemExit(f"[error] Input file not found: {inp}")

    outp.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(outp), pagesize=(PAGE_W, PAGE_H))

    with open(inp, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f, delimiter="\t")
        count = 0
        for row in reader:
            if not row or all(not (x or "").strip() for x in row):
                continue
            while len(row) < 4:
                row.append("")
            title, price, inv_id, barcode_val = [x.strip() for x in row[:4]]
            draw_label(c, title, price, inv_id, barcode_val)
            c.showPage()
            count += 1

    c.save()
    print(f"Done: {outp} ({count} labels)")


if __name__ == "__main__":
    main()
