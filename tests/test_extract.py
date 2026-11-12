"""Extraction checks in code (no model): arithmetic, formats, and the second-source cross-check."""

from decimal import Decimal

from p2p_autopilot.extract import _amounts, _dates, cross_check, extract, pdf_text, portal_context, validate
from p2p_autopilot.matching import DocLine, ExtractedDoc

GOOD = {"doc_type": "invoice", "number": "INV-1067", "po_number": "PO-5530", "issue_date": "2026-10-03",
        "due_date": "2026-11-02", "total": "966.00", "lines": [{"sku": "TR-M12-1M", "qty": 200, "unit_price": "4.83"}]}


def test_valid_document_passes():
    doc, errors = validate(GOOD, "SUP-ACME")
    assert errors == [] and doc.total == Decimal("966.00") and doc.lines[0].qty == 200


def test_arithmetic_error_is_caught():
    _, errors = validate({**GOOD, "total": "996.00"}, "SUP-ACME")
    assert any("add up to 966.00" in e for e in errors)


def test_european_number_and_bad_date_are_caught():
    _, errors = validate({**GOOD, "total": "966,00", "issue_date": "03.10.2026"}, "SUP-ACME")
    assert any("plain decimal" in e for e in errors) and any("ISO" in e for e in errors)


def test_unsigned_credit_note_gets_negative_total():
    doc, errors = validate({**GOOD, "doc_type": "credit_note"}, "SUP-ACME")
    assert errors == [] and doc.total == Decimal("-966.00")


def test_amount_and_date_parsing_handles_us_and_european():
    assert {Decimal("2119.50"), Decimal("4325.55")} <= _amounts("$2,119.50 and 4.325,55 USD")
    assert {"2026-10-24", "2026-10-28", "2026-10-03"} <= _dates("10/24/2026 28.10.2026 2026-10-03")


def doc(total="966.00", po="PO-5530", day="2026-10-03"):
    return ExtractedDoc("SUP-ACME", "INV-1067", "invoice", po, day, Decimal(total),
                        (DocLine("TR-M12-1M", 200, Decimal("4.83")),))


ROW = '- row "INV-1067 10/03/2026 PO-5530 $966.00 OPEN View PDF":'


def test_cross_check_agrees_with_matching_row():
    assert cross_check(doc(), portal_context(f"- table:\n  {ROW}", "INV-1067"))[0] == "agree"


def test_cross_check_flags_wrong_total_po_or_date():
    ctx = portal_context(ROW, "INV-1067")
    for d in (doc(total="996.00"), doc(po="PO-5531"), doc(day="2026-03-10")):
        check, notes = cross_check(d, ctx)
        assert check == "disagree" and notes


def test_details_popup_context_uses_nearby_lines():
    popup = "- heading \"Rechnung / Invoice\"\n- text: \"Nr.: VX/2026/0338\"\n- text: \"Datum: 28.10.2026\"\n" \
            "- text: \"Bestellung / Order: PO-5624\"\n- text: \"Betrag / Amount: 4.325,55 USD\""
    d = ExtractedDoc("SUP-VALVEX", "VX/2026/0338", "invoice", "PO-5624", "2026-10-28", Decimal("4325.55"),
                     (DocLine("BV-050", 1, Decimal("4325.55")),))
    assert cross_check(d, portal_context(popup, "VX/2026/0338"))[0] == "agree"


def test_month_name_dates_are_understood():
    assert {"2026-10-03", "2026-09-28"} <= _dates("Date issued 3 Oct 2026 · Sept 28, 2026")


class FakeBackend:
    def __init__(self, data):
        self.data, self.calls = data, []

    def complete(self, system, prompt, schema, model="haiku", images=None):
        from p2p_autopilot.llm import LLMResult
        self.calls.append(images)
        return LLMResult(self.data, 100, 10, 0.1, model)


def test_scan_without_text_layer_is_read_from_images(tmp_path, monkeypatch):
    """D14: a scanned PDF has no text layer, so extraction sends page images; the same checks still run."""
    from p2p_autopilot.portals.app import DOCS, SUPPLIERS
    from p2p_autopilot.portals.pdf import render, scanned
    monkeypatch.setenv("LPA_NO_EXTRACT_CACHE", "1")
    d = next(x for x in DOCS["a"] if x["status"] == "open" and x["doc_type"] == "invoice")
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(scanned(render(d, SUPPLIERS["a"]), d["number"]))
    assert pdf_text(pdf).strip() == ""
    raw = {"doc_type": "invoice", "number": d["number"], "po_number": d["po_number"], "issue_date": d["issue_date"],
           "due_date": d["due_date"], "total": d["total"],
           "lines": [{"sku": ln["sku"], "qty": ln["qty"], "unit_price": ln["unit_price"]} for ln in d["lines"]]}
    fake = FakeBackend(raw)
    ex = extract(pdf, "SUP-ACME", fake)
    assert ex.source == "image" and ex.errors == [] and fake.calls[0] and fake.calls[0][0][:4] == b"\x89PNG"


def test_text_pdf_does_not_send_images(tmp_path, monkeypatch):
    from p2p_autopilot.portals.app import DOCS, SUPPLIERS
    from p2p_autopilot.portals.pdf import render
    monkeypatch.setenv("LPA_NO_EXTRACT_CACHE", "1")
    d = next(x for x in DOCS["a"] if x["status"] == "open")
    pdf = tmp_path / "text.pdf"
    pdf.write_bytes(render(d, SUPPLIERS["a"]))
    fake = FakeBackend({**GOOD})
    assert extract(pdf, "SUP-ACME", fake).source == "text" and fake.calls == [None]


def test_tests_never_write_the_real_cache(tmp_path):
    from p2p_autopilot import extract
    assert "runs" not in extract.CACHE_DIR.parts  # conftest points every test at a temporary cache
