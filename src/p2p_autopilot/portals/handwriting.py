"""Handwriting on printed invoices, the way it shows up in real accounts payable (D15).

Fully handwritten B2B invoices are rare; ink ON printed invoices is common. Three kinds, planted deterministically
per document so evals are repeatable and every expected outcome is known:

  amount_correction  the printed total is struck through and a lower total is written next to it. The amount is in
                     doubt, so the only safe outcome is a human review (never pay either number automatically).
  approval           "OK to pay" + initials and a date in the margin. Harmless for the numbers, and NOT an approval:
                     only the review console approves.
  note               "rec'd, checked" style remark. Harmless.

The page is then scanned (see pdf.scanned), so the ink can only be read from the image.
"""

from __future__ import annotations

import hashlib
import random
from decimal import Decimal
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont

FONT = Path(__file__).parent / "fonts" / "Caveat.ttf"  # SIL Open Font License (fonts/OFL.txt)
INK = (25, 45, 140)
DPI = 150
KINDS = ("amount_correction", "approval", "note")


def plan(number: str, doc_type: str) -> str | None:
    """Which handwriting a document gets (None = clean). About 1 in 4 invoices gets an amount correction."""
    r = random.Random(hashlib.sha256(f"hw|{number}".encode()).hexdigest()).random()
    if r < 0.25 and doc_type == "invoice":
        return "amount_correction"
    if r < 0.50:
        return "approval"
    if r < 0.70:
        return "note"
    return None


def corrected_total(doc: dict) -> Decimal:
    rng = random.Random(hashlib.sha256(f"hwtotal|{doc['number']}".encode()).hexdigest())
    return (Decimal(doc["total"]) * Decimal(str(rng.choice([0.9, 0.92, 0.95, 0.97])))).quantize(Decimal(1))


def _box(page, text: str) -> tuple[float, float, float, float] | None:
    """Pixel box (left, top, right, bottom) of the LAST occurrence of text on the page (the Total row)."""
    tp = page.get_textpage()
    searcher, hit = tp.search(text), None
    while (h := searcher.get_next()) is not None:
        hit = h
    if hit is None:
        return None
    boxes = [tp.get_charbox(i) for i in range(hit[0], hit[0] + hit[1])]
    height, s = page.get_size()[1], DPI / 72
    left, right = min(b[0] for b in boxes), max(b[2] for b in boxes)
    bottom, top = min(b[1] for b in boxes), max(b[3] for b in boxes)
    return left * s, (height - top) * s, right * s, (height - bottom) * s


def annotate(pdf_bytes: bytes, doc: dict, total_text: str) -> list[Image.Image]:
    """Page images at DPI with this document's planted handwriting drawn on in blue ink."""
    kind = plan(doc["number"], doc["doc_type"])
    rng = random.Random(hashlib.sha256(f"hwpos|{doc['number']}".encode()).hexdigest())
    pages = [p.render(scale=DPI / 72).to_pil().convert("RGB") for p in pdfium.PdfDocument(pdf_bytes)]
    img, draw = pages[0], ImageDraw.Draw(pages[0])
    font = ImageFont.truetype(str(FONT), 34)
    small = ImageFont.truetype(str(FONT), 28)
    w, h = img.size
    if kind == "amount_correction":
        box = _box(pdfium.PdfDocument(pdf_bytes)[0], total_text)
        if box:
            left, top, right, bottom = box
            mid = (top + bottom) / 2
            draw.line([(left - 6, mid + 2), (right + 6, mid - 3)], fill=INK, width=3)
            draw.line([(left - 6, mid + 6), (right + 6, mid + 1)], fill=INK, width=2)
            note = f"{corrected_total(doc):,}.00  per call w/ Dana"
            x = min(max(left - 40, 20), w - draw.textlength(note, font=font) - 20)  # stay on the page
            draw.text((x, bottom + 6), note, font=font, fill=INK)
    elif kind == "approval":
        x, y = int(w * rng.uniform(0.55, 0.65)), int(h * rng.uniform(0.82, 0.88))
        draw.text((x, y), "OK to pay", font=font, fill=INK)
        draw.text((x + 10, y + 38), f"JR  {rng.randint(1, 28)}/{rng.choice([10, 11])}", font=small, fill=INK)
    elif kind == "note":
        x, y = int(w * rng.uniform(0.08, 0.2)), int(h * rng.uniform(0.84, 0.9))
        draw.text((x, y), rng.choice(["rec'd - checked vs PO", "filed  #AP", "pls scan to Dana"]), font=font,
                  fill=INK)
    return pages
