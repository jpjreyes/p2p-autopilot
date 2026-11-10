"""PDF -> structured fields: the model reads, code checks (decision D8 = C).

1. Text comes out of the PDF with pypdf (our PDFs have a text layer; scanned paper would need OCR or vision).
2. The model fills a JSON schema: number, type, PO, dates, lines, total. Money comes back as strings.
3. Code validates: required fields, numbers parse, dates are real ISO dates, quantity x price adds up to the total.
4. Second source: the portal's own listing row (or details pop-up) seen at download time must agree on number,
   total, PO and date.
5. A failed arithmetic/format check gets ONE retry with the errors spelled out; still failing -> human review.
   A disagreement with the portal row is never retried: it goes straight to a human (two sources disagree).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pypdfium2 as pdfium
from pypdf import PdfReader

from legacy_portal.llm import DEFAULT_MODEL, Backend
from legacy_portal.matching import DocLine, ExtractedDoc

CENT = Decimal("0.01")
CACHE_DIR = Path(__file__).resolve().parents[2] / "runs" / ".extract_cache"

SYSTEM = """You extract fields from supplier invoices and credit notes for accounts payable.
Return exactly what the document says; never compute or guess values that are not printed.
- doc_type: "credit_note" if the document is a credit memo / credit note / Gutschrift, else "invoice".
- number: the document number exactly as printed.
- po_number: the buyer's purchase order reference (may be labeled PO, Your PO, Bestellung, Customer reference).
- issue_date and due_date as ISO YYYY-MM-DD. Read the date format from the document's conventions
  (US MM/DD/YYYY, European DD.MM.YYYY, or ISO).
- Money as plain decimal strings with a dot and no thousands separators: "1234.50". Convert European formats
  ("1.234,50" -> "1234.50"). Keep the sign as printed (credit notes are usually negative).
- lines: one entry per item row: sku, qty (integer), unit_price (positive string)."""

SCHEMA = {
    "type": "object",
    "properties": {
        "doc_type": {"type": "string", "enum": ["invoice", "credit_note"]},
        "number": {"type": "string"},
        "po_number": {"type": "string"},
        "issue_date": {"type": "string"},
        "due_date": {"type": "string"},
        "total": {"type": "string"},
        "lines": {"type": "array", "items": {"type": "object", "properties": {
            "sku": {"type": "string"}, "qty": {"type": "integer"}, "unit_price": {"type": "string"}},
            "required": ["sku", "qty", "unit_price"]}},
    },
    "required": ["doc_type", "number", "po_number", "issue_date", "total", "lines"],
}


@dataclass
class Extraction:
    pdf: str
    doc: ExtractedDoc | None
    raw: dict
    errors: list[str]              # format/arithmetic problems left after the retry
    portal_check: str              # "agree" | "disagree" | "unavailable"
    portal_notes: list[str] = field(default_factory=list)
    attempts: int = 1
    tokens_in: int = 0
    latency_s: float = 0.0
    tokens_out: int = 0
    source: str = "text"           # "text" (PDF text layer) | "image" (scan read from page images, D14)

    @property
    def needs_human(self) -> bool:
        return bool(self.errors) or self.portal_check == "disagree" or self.doc is None


def pdf_text(path: str | Path) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)


MIN_TEXT_CHARS = 30  # less than this = no usable text layer (a scan): read the page images instead (D14)
MAX_PAGES = 3


def page_images(path: str | Path, dpi: int = 150) -> list[bytes]:
    """PNG of each page (up to MAX_PAGES), for scanned documents with no text layer."""
    out = []
    for page in list(pdfium.PdfDocument(str(path)))[:MAX_PAGES]:
        buf = io.BytesIO()
        page.render(scale=dpi / 72).to_pil().convert("L").save(buf, "PNG", optimize=True)
        out.append(buf.getvalue())
    return out


def _dec(value: str, what: str, errors: list[str]) -> Decimal | None:
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        errors.append(f"{what} {value!r} is not a plain decimal like 1234.50")
        return None


def validate(raw: dict, supplier_id: str) -> tuple[ExtractedDoc | None, list[str]]:
    """Format and arithmetic checks. Returns the typed document (if parseable) and every problem found."""
    errors: list[str] = []
    for key in ("number", "po_number", "issue_date", "total"):
        if not str(raw.get(key, "")).strip():
            errors.append(f"missing {key}")
    try:
        date.fromisoformat(raw.get("issue_date", ""))
    except ValueError:
        errors.append(f"issue_date {raw.get('issue_date')!r} is not ISO YYYY-MM-DD")
    total = _dec(raw.get("total", ""), "total", errors)
    lines: list[DocLine] = []
    for i, ln in enumerate(raw.get("lines") or []):
        price = _dec(ln.get("unit_price", ""), f"line {i + 1} unit_price", errors)
        qty = ln.get("qty")
        if not isinstance(qty, int) or qty <= 0:
            errors.append(f"line {i + 1} qty {qty!r} must be a positive integer")
            continue
        if price is not None:
            lines.append(DocLine(str(ln.get("sku", "")).strip(), qty, abs(price)))
    if not lines:
        errors.append("no item lines found")
    if total is not None and lines:
        line_sum = sum((ln.qty * ln.unit_price for ln in lines), Decimal(0)).quantize(CENT)
        if line_sum != abs(total).quantize(CENT):
            errors.append(f"lines add up to {line_sum} but the total says {total}")
        if raw.get("doc_type") == "credit_note" and total > 0:
            total = -total  # some suppliers print credit totals unsigned; the document type decides the sign
    if errors:
        return None, errors
    doc = ExtractedDoc(supplier_id, raw["number"].strip(), raw["doc_type"], raw["po_number"].strip(),
                       raw["issue_date"], total.quantize(CENT), tuple(lines))
    return doc, []


# ------------------------------------------------------------------ second source: the portal's own listing

_MONEY = re.compile(r"-?\$?\s?-?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})")
_DATE_FORMATS = ("%m/%d/%Y", "%d.%m.%Y", "%Y-%m-%d")


def _amounts(text: str) -> set[Decimal]:
    out = set()
    for m in _MONEY.findall(text):
        s = m.replace("$", "").replace(" ", "")
        neg = s.startswith("-")
        s = s.lstrip("-")
        if re.search(r",\d{2}$", s):          # European 1.234,50
            s = s.replace(".", "").replace(",", ".")
        else:                                   # US 1,234.50
            s = s.replace(",", "")
        try:
            out.add(abs(Decimal(s)) * (-1 if neg else 1))
        except InvalidOperation:
            continue
    return out


_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"


def _dates(text: str) -> set[str]:
    out = set()
    # Month-name formats: "3 Oct 2026", "03 October 2026", "Oct 3, 2026"
    for day, mon, year in re.findall(rf"\b(\d{{1,2}}) ({_MONTHS})[a-z]* (\d{{4}})\b", text, flags=re.IGNORECASE):
        out.add(datetime.strptime(f"{day} {mon[:3].title()} {year}", "%d %b %Y").date().isoformat())
    for mon, day, year in re.findall(rf"\b({_MONTHS})[a-z]* (\d{{1,2}}),? (\d{{4}})\b", text, flags=re.IGNORECASE):
        out.add(datetime.strptime(f"{day} {mon[:3].title()} {year}", "%d %b %Y").date().isoformat())
    for tok in re.findall(r"\d{1,4}[./-]\d{1,2}[./-]\d{2,4}", text):
        for fmt in _DATE_FORMATS:
            try:
                out.add(datetime.strptime(tok, fmt).date().isoformat())
            except ValueError:
                continue
    return out


def portal_context(snapshot: str, number: str) -> str | None:
    """The part of the page (seen at download time) that describes this document: its table row, or the
    details pop-up lines around the number."""
    lines = snapshot.splitlines()
    for i, line in enumerate(lines):
        if number in line:
            if line.lstrip().startswith("- row"):
                return line
            return "\n".join(lines[max(0, i - 3): i + 8])
    return None


def cross_check(doc: ExtractedDoc, context: str | None) -> tuple[str, list[str]]:
    if not context:
        return "unavailable", ["portal row not captured for this document"]
    notes = []
    amounts = _amounts(context)
    if doc.total not in amounts and abs(doc.total) not in amounts:
        notes.append(f"total {doc.total} not shown on the portal row ({sorted(amounts)})")
    if doc.po_number not in context:
        notes.append(f"PO {doc.po_number} not shown on the portal row")
    if doc.issue_date not in _dates(context):
        notes.append(f"issue date {doc.issue_date} not shown on the portal row")
    return ("disagree" if notes else "agree"), notes


def extract(pdf: str | Path, supplier_id: str, backend: Backend, context_snapshot: str | None = None,
            model: str = DEFAULT_MODEL) -> Extraction:
    text = pdf_text(pdf)
    images = page_images(pdf) if len(text.strip()) < MIN_TEXT_CHARS else None
    source = "image" if images else "text"
    content = Path(pdf).read_bytes() if images else text.encode()
    key = hashlib.sha256(f"{model}|".encode() + content).hexdigest()[:24]
    cached = CACHE_DIR / f"{key}.json"
    # identical PDF already read and validated: reuse the model output, re-run every check
    # (LPA_NO_EXTRACT_CACHE=1 forces fresh model reads, e.g. to measure cost)
    if cached.exists() and not os.environ.get("LPA_NO_EXTRACT_CACHE"):
        raw = json.loads(cached.read_text())
        doc, errors = validate(raw, supplier_id)
        if doc is not None:
            check, notes = cross_check(doc, portal_context(context_snapshot or "", doc.number))
            return Extraction(str(pdf), doc, raw, [], check, notes, 0, 0, 0.0, source=source)
    prompt = (f"Document text:\n---\n{text}\n---" if not images else
              "The document is a scan with no text layer; its page images are attached. Read every field from the "
              "images. If a character is unreadable, give your best reading: arithmetic checks run afterwards.")
    res = backend.complete(SYSTEM, prompt, SCHEMA, model=model, images=images)
    tokens, latency, attempts, out_tokens = res.input_tokens, res.latency_s, 1, res.output_tokens
    doc, errors = validate(res.data, supplier_id)
    if errors:  # one retry, with the problems spelled out
        retry = (f"{prompt}\n\nYour previous answer:\n{res.data}\n\nIt failed these checks:\n- " + "\n- ".join(errors)
                 + "\nRe-read the document and answer again. Only change what the document supports.")
        res = backend.complete(SYSTEM, retry, SCHEMA, model=model, images=images)
        tokens, latency, attempts = tokens + res.input_tokens, latency + res.latency_s, 2
        out_tokens += res.output_tokens
        doc, errors = validate(res.data, supplier_id)
    if doc is None:
        return Extraction(str(pdf), None, res.data, errors, "unavailable", [], attempts, tokens, latency,
                          out_tokens, source)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(res.data))
    context = portal_context(context_snapshot or "", doc.number)
    check, notes = cross_check(doc, context)
    return Extraction(str(pdf), doc, res.data, [], check, notes, attempts, tokens, latency, out_tokens, source)
