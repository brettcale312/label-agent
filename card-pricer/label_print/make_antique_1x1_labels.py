# make_antique_1x1_labels.py
# 1" x 1" label with Code 128 barcode for small antique items / hang tags.
#
# Layout (top → bottom):
#   Price    — large, bold, centered
#   Title    — small, centered, word-wraps to 2 lines
#   Barcode  — Code 128, fills the remaining height
#   Footer   — booth number (left)  ·  inventory ID (right)
#
# Input TSV columns (5):
#   Title, Price, InventoryID, BarcodeNumber, BoothNumber
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


def normalize(s: str) -> str:
    return (s or "").replace("–", "-").replace("—", "-").replace(" ", " ")


def _wrap_title(c_obj, text: str, font: str, size: float, max_w: float) -> list[str]:
    """Word-wrap *text* into at most 2 centred lines that each fit max_w."""
    if not text:
        return []
    words = text.split()

    line1_words: list[str] = []
    remaining_start = 0
    for i, word in enumerate(words):
        candidate = " ".join(line1_words + [word])
        if c_obj.stringWidth(candidate, font, size) <= max_w:
            line1_words.append(word)
            remaining_start = i + 1
        else:
            break

    if remaining_start >= len(words):
        return [" ".join(line1_words)]

    line1 = " ".join(line1_words)
    line2 = " ".join(words[remaining_start:])
    while line2 and c_obj.stringWidth(line2, font, size) > max_w:
        if " " in line2:
            line2 = line2.rsplit(" ", 1)[0]
        else:
            line2 = line2[:-1]
    return [line1, line2.strip()] if line2.strip() else [line1]


def draw_label(c, title: str, price: str, inv_id: str, barcode_val: str, booth: str):
    title       = normalize(title)
    price       = normalize(price)
    inv_id      = normalize(inv_id)
    barcode_val = normalize(barcode_val)
    booth       = normalize(booth)

    if not barcode_val:
        return  # nothing to encode

    usable_w = PAGE_W - 2 * MARGIN
    cx = PAGE_W / 2   # centre x

    # ── Price — large, bold, centred at top ───────────────────────────────
    price_size = 10
    price_y = PAGE_H - MARGIN - price_size
    c.setFont("Helvetica-Bold", price_size)
    c.drawCentredString(cx, price_y, price)

    # ── Title — small, centred, up to 2 lines ─────────────────────────────
    title_font, title_size = "Helvetica", 5
    c.setFont(title_font, title_size)
    lines = _wrap_title(c, title, title_font, title_size, usable_w)

    title_leading = 1          # pt between wrapped lines
    title_top_y = price_y - price_size - 2    # first baseline, just below price
    for i, line in enumerate(lines):
        y = title_top_y - i * (title_size + title_leading)
        c.drawCentredString(cx, y, line)

    # Bottom of the last title line
    last_title_bottom = title_top_y - (len(lines) - 1) * (title_size + title_leading)

    # ── Footer — booth left, inv ID right (bare numbers, no labels) ────────
    foot_font, foot_size = "Helvetica", 5
    c.setFont(foot_font, foot_size)
    foot_y = MARGIN
    if booth:
        c.drawString(MARGIN, foot_y, booth)
    if inv_id:
        inv_w = c.stringWidth(inv_id, foot_font, foot_size)
        c.drawString(PAGE_W - MARGIN - inv_w, foot_y, inv_id)

    # ── Barcode — Code 128, fills space between title and footer ───────────
    bc_bottom = foot_y + foot_size + 2          # 2pt gap above footer
    bc_top    = last_title_bottom - title_size - 2   # 2pt gap below title
    bc_h      = max(bc_top - bc_bottom, 8)

    bc = code128.Code128(
        barcode_val,
        barHeight=bc_h,
        barWidth=0.009 * inch,
        humanReadable=False,
    )
    bc_x = max(MARGIN, (PAGE_W - bc.width) / 2)
    bc.drawOn(c, bc_x, bc_bottom)


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
            while len(row) < 5:
                row.append("")
            title, price, inv_id, barcode_val, booth = [x.strip() for x in row[:5]]
            draw_label(c, title, price, inv_id, barcode_val, booth)
            c.showPage()
            count += 1

    c.save()
    print(f"Done: {outp} ({count} labels)")


if __name__ == "__main__":
    main()
