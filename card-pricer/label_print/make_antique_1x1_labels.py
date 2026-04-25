# make_antique_1x1_labels.py
# 1" x 1" label with QR code for small antique items / hang tags.
#
# Code 128 barcodes need ~0.75" min width to scan reliably — too wide for 1"
# labels with any text beside them. QR codes scale down much better and scan
# from a phone at this size.
#
# Input TSV columns (4):
#   Title, Price, InventoryID, BarcodeNumber
#   (BarcodeNumber is encoded into the QR — same value Quail/Sandpiper uses)
#
# Requires: reportlab + qrcode[pil]   (pip install qrcode[pil])
#
# Usage:
#   python make_antique_1x1_labels.py input.tsv output.pdf

import csv
import io
import sys
from pathlib import Path

from reportlab.pdfgen import canvas
from reportlab.lib.units import inch

try:
    import qrcode
    from PIL import Image as PILImage
except ImportError:
    raise SystemExit(
        "[error] Missing dependency: pip install 'qrcode[pil]'\n"
        "Add qrcode[pil]>=7.0 to requirements.txt if running on Railway."
    )

PAGE_W = 1 * inch
PAGE_H = 1 * inch
MARGIN = 0.05 * inch


def _make_qr_image(data: str) -> PILImage.Image:
    qr = qrcode.QRCode(
        version=None,           # auto-size
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=1,               # minimal quiet zone — we add our own margin
    )
    qr.add_data(data)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")


def draw_label(c, title: str, price: str, inv_id: str, barcode_val: str):
    title      = (title or "").strip()
    price      = (price or "").strip()
    inv_id     = (inv_id or "").strip()
    barcode_val = (barcode_val or "").strip()

    if not barcode_val:
        return  # nothing to encode

    # ── Layout ────────────────────────────────────────────────────────────
    # Left half: QR code
    # Right half: price (top) + inv ID (bottom), stacked

    qr_size = PAGE_H - 2 * MARGIN          # square, nearly full height
    qr_x    = MARGIN
    qr_y    = MARGIN

    right_x  = qr_x + qr_size + 3          # 3pt gap after QR
    right_w  = PAGE_W - right_x - MARGIN

    # Draw QR code as an image
    img = _make_qr_image(barcode_val)
    img_bytes = io.BytesIO()
    img.save(img_bytes, format="PNG")
    img_bytes.seek(0)
    c.drawImage(
        img_bytes,                          # type: ignore[arg-type]
        qr_x, qr_y,
        width=qr_size, height=qr_size,
        preserveAspectRatio=True,
    )

    # ── Price (upper-right, bold) ──────────────────────────────────────────
    price_font, price_size = "Helvetica-Bold", 7
    c.setFont(price_font, price_size)
    # Truncate if needed
    disp_price = price
    while disp_price and c.stringWidth(disp_price, price_font, price_size) > right_w:
        disp_price = disp_price[:-1]
    c.drawString(right_x, qr_y + qr_size - price_size - 1, disp_price)

    # ── Title (middle, small) ──────────────────────────────────────────────
    title_font, title_size = "Helvetica", 5
    c.setFont(title_font, title_size)
    disp_title = title
    while disp_title and c.stringWidth(disp_title, title_font, title_size) > right_w:
        disp_title = disp_title[:-1]
    c.drawString(right_x, qr_y + qr_size - price_size - title_size - 4, disp_title)

    # ── Inv ID (bottom-right, tiny) ────────────────────────────────────────
    inv_font, inv_size = "Helvetica", 5
    c.setFont(inv_font, inv_size)
    disp_inv = inv_id
    while disp_inv and c.stringWidth(disp_inv, inv_font, inv_size) > right_w:
        disp_inv = disp_inv[:-1]
    c.drawString(right_x, qr_y + 2, disp_inv)


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
