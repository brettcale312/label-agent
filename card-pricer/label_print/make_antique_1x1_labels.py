# make_antique_1x1_labels.py
# 1" x 1" label with Code 128 barcode for small antique items / hang tags.
#
# The barcode fills most of the label height so it can scan from a phone
# or handheld scanner at this size.  Price and title appear above; inventory
# ID appears below the barcode.
#
# Input TSV columns (4):
#   Title, Price, InventoryID, BarcodeNumber
#
# Requires: reportlab   (pip install reportlab)
#
# Usage:
#   python make_antique_1x1_labels.py input.tsv output.pdf

import csv
import sys
from pathlib import Path

from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.graphics.barcode import code128

PAGE_W = 1 * inch
PAGE_H = 1 * inch
MARGIN = 0.05 * inch


def draw_label(c, title: str, price: str, inv_id: str, barcode_val: str):
    title       = (title       or "").strip()
    price       = (price       or "").strip()
    inv_id      = (inv_id      or "").strip()
    barcode_val = (barcode_val or "").strip()

    if not barcode_val:
        return  # nothing to encode

    # ── Top row: title (left) + price (right, bold) ───────────────────────
    top_size  = 7
    top_y     = PAGE_H - MARGIN - top_size      # baseline

    price_font = "Helvetica-Bold"
    c.setFont(price_font, top_size)
    price_w = c.stringWidth(price, price_font, top_size)
    c.drawString(PAGE_W - MARGIN - price_w, top_y, price)

    title_font = "Helvetica"
    c.setFont(title_font, top_size)
    title_max_w = PAGE_W - 2 * MARGIN - price_w - 3   # 3pt gap
    disp_title = title
    while disp_title and c.stringWidth(disp_title, title_font, top_size) > title_max_w:
        disp_title = disp_title[:-1]
    c.drawString(MARGIN, top_y, disp_title)

    # ── Bottom row: inventory ID ───────────────────────────────────────────
    bot_size = 5
    bot_y    = MARGIN                              # baseline

    c.setFont("Helvetica", bot_size)
    c.drawString(MARGIN, bot_y, f"ID: {inv_id}")

    # ── Barcode (Code128, fills the space between top and bottom rows) ─────
    # Compute available height dynamically
    bc_y   = bot_y + bot_size + 2           # 2pt gap above ID text
    bc_top = top_y - 2                      # 2pt gap below top text
    bc_h   = max(bc_top - bc_y, 8)         # guard against tiny labels

    bc = code128.Code128(
        barcode_val,
        barHeight=bc_h,
        barWidth=0.009 * inch,              # narrow bar — fits in 1" width
        humanReadable=False,
    )
    # Center horizontally; clamp to margin if wider than label
    bc_x = max(MARGIN, (PAGE_W - bc.width) / 2)
    bc.drawOn(c, bc_x, bc_y)


def main():
    if len(sys.argv) >= 3:
        inp  = Path(sys.argv[1])
        outp = Path(sys.argv[2])
    else:
        here = Path(__file__).resolve().parent
        inp  = here / "antique_1x1_input.txt"
        outp = here / "antique_1x1_label.pdf"
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
