# make_antique_2x1_labels.py
# 2" x 1" label — word-wrapped title, price, Code 128 barcode, ID + Booth footer.
# Designed for Rollo thermal printer.
#
# Input TSV columns (5):
#   Title, Price, InventoryID, BarcodeNumber, BoothNumber
#
# Usage:
#   python make_antique_2x1_labels.py input.tsv output.pdf

import csv
import sys
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.graphics.barcode import code128

PAGE_W    = 2 * inch
PAGE_H    = 1 * inch
MARGIN    = 0.08 * inch
BARCODE_H = 0.28 * inch


def normalize(s: str) -> str:
    return (s or "").replace("–", "-").replace("—", "-").replace(" ", " ")


def _wrap_title(
    c_obj,
    text: str,
    font: str,
    size: float,
    max_w_line1: float,
    max_w_line2: float,
) -> list[str]:
    """
    Word-wrap *text* into at most 2 lines.
    Line 1 is limited to max_w_line1 (leaves room for price on the right).
    Line 2 uses the full max_w_line2.
    Long single words are truncated by character rather than dropped.
    """
    if not text:
        return [""]
    words = text.split()

    # ── Build line 1 greedily ─────────────────────────────────────────────
    line1_words: list[str] = []
    remaining_start = 0
    for i, word in enumerate(words):
        candidate = " ".join(line1_words + [word])
        if c_obj.stringWidth(candidate, font, size) <= max_w_line1:
            line1_words.append(word)
            remaining_start = i + 1
        else:
            break  # remaining_start correctly points at the first word that didn't fit

    if remaining_start >= len(words):
        # Everything fitted on one line
        return [" ".join(line1_words)]

    line1 = " ".join(line1_words)

    # ── Build line 2 from remaining words ────────────────────────────────
    line2 = " ".join(words[remaining_start:])
    # Trim by word first, then by character if a single word is too wide
    while line2 and c_obj.stringWidth(line2, font, size) > max_w_line2:
        if " " in line2:
            line2 = line2.rsplit(" ", 1)[0]
        else:
            line2 = line2[:-1]

    return [line1, line2.strip()] if line2.strip() else [line1]


def draw_label(
    c,
    title: str,
    price: str,
    inv_id: str,
    barcode_val: str,
    booth: str,
) -> None:
    title       = normalize(title)
    price       = normalize(price)
    inv_id      = normalize(inv_id)
    barcode_val = normalize(barcode_val)
    booth       = normalize(booth)

    usable_w = PAGE_W - 2 * MARGIN

    # ── Footer: ID left, Booth right ──────────────────────────────────────
    foot_font, foot_size = "Helvetica", 6
    c.setFont(foot_font, foot_size)
    foot_y = MARGIN
    if inv_id:
        c.drawString(MARGIN, foot_y, f"ID: {inv_id}")
    if booth:
        booth_str = f"Booth: {booth}"
        booth_w = c.stringWidth(booth_str, foot_font, foot_size)
        c.drawString(PAGE_W - MARGIN - booth_w, foot_y, booth_str)

    # ── Barcode (centered, just above footer) ─────────────────────────────
    if barcode_val:
        bc = code128.Code128(
            barcode_val,
            barHeight=BARCODE_H,
            barWidth=0.016 * inch,
            humanReadable=False,
        )
        bc_x = (PAGE_W - bc.width) / 2
        bc_y = foot_y + foot_size + 2          # 2pt gap above footer text
        bc.drawOn(c, bc_x, bc_y)

    # ── Price (top-right, bold) ────────────────────────────────────────────
    price_font, price_size = "Helvetica-Bold", 9
    c.setFont(price_font, price_size)
    price_w  = c.stringWidth(price, price_font, price_size)
    title_y1 = PAGE_H - MARGIN - price_size    # baseline of the top text row
    c.drawString(PAGE_W - MARGIN - price_w, title_y1, price)

    # ── Title (word-wrapped, up to 2 lines, bold) ──────────────────────────
    title_font, title_size = "Helvetica-Bold", 9
    c.setFont(title_font, title_size)
    GAP = 4           # pt gap between title and price on line 1
    max_w_line1 = usable_w - price_w - GAP
    max_w_line2 = usable_w
    lines = _wrap_title(c, title, title_font, title_size, max_w_line1, max_w_line2)

    line_leading = 2  # extra leading between wrapped lines
    for i, line in enumerate(lines):
        y = title_y1 - i * (title_size + line_leading)
        c.drawString(MARGIN, y, line)


def main() -> None:
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
