"""Invoice PDFs, one visual style per supplier (the extraction step must cope with all three)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fpdf import FPDF


def _fmt_money(value: str, portal: str) -> str:
    d = Decimal(value)
    if portal == "d":  # USD 1,234.50
        return f"USD {'-' if d < 0 else ''}{abs(d):,.2f}"
    if portal == "b":  # European format: 1.234,50
        s = f"{abs(d):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return ("-" if d < 0 else "") + s + " USD"
    return f"{'-' if d < 0 else ''}${abs(d):,.2f}"


def fmt_date(iso: str, portal: str) -> str:
    d = date.fromisoformat(iso)
    return {"a": d.strftime("%m/%d/%Y"), "b": d.strftime("%d.%m.%Y"), "c": d.isoformat(),
            "d": f"{d.day} {d.strftime('%b %Y')}"}[portal]


def fmt_money(value: str, portal: str) -> str:
    return _fmt_money(value, portal)


def render(doc: dict, supplier: dict) -> bytes:
    portal = doc["portal"]
    pdf = FPDF(format="Letter")
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()
    title = "CREDIT MEMO" if doc["doc_type"] == "credit_note" else "INVOICE"

    if portal == "a":  # plain, left-aligned, all caps header
        pdf.set_font("Courier", "B", 16)
        pdf.cell(0, 10, supplier["name"].upper(), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Courier", "", 10)
        pdf.cell(0, 5, "1200 Industrial Pkwy, Dayton OH 45402", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)
        pdf.set_font("Courier", "B", 14)
        pdf.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Courier", "", 10)
        meta = [("Invoice No.", doc["number"]), ("Date", fmt_date(doc["issue_date"], portal)),
                ("Due", fmt_date(doc["due_date"], portal)), ("Your PO", doc["po_number"])]
    elif portal == "b":  # German-style letterhead, meta block on the right
        pdf.set_font("Helvetica", "B", 18)
        pdf.cell(0, 10, supplier["name"], align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 5, "Industriestrasse 14, 70565 Stuttgart, Germany", align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(6)
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 8, "Rechnung / " + ("Gutschrift / Credit Note" if title == "CREDIT MEMO" else "Invoice"),
                 new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        meta = [("Rechnungs-Nr. / Invoice no.", doc["number"]), ("Datum / Date", fmt_date(doc["issue_date"], portal)),
                ("Faellig / Due", fmt_date(doc["due_date"], portal)), ("Ihre Bestellung / Your order", doc["po_number"])]
    elif portal == "d":  # statement style
        pdf.set_font("Times", "B", 15)
        pdf.cell(0, 9, supplier["name"], new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Times", "", 11)
        pdf.cell(0, 6, "Statement of account - " + ("Credit" if title == "CREDIT MEMO" else "Charge"),
                 new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        meta = [("Statement no.", doc["number"]), ("Date issued", fmt_date(doc["issue_date"], portal)),
                ("Pay by", fmt_date(doc["due_date"], portal)), ("Your reference", doc["po_number"])]
    else:  # modern, but meta in a box
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, f"{supplier['name']} - {title.title()}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        meta = [("Document", doc["number"]), ("Issued", fmt_date(doc["issue_date"], portal)),
                ("Payment due", fmt_date(doc["due_date"], portal)), ("Customer reference", doc["po_number"])]

    for k, v in meta:
        pdf.cell(70, 6, k + ":")
        pdf.cell(0, 6, v, new_x="LMARGIN", new_y="NEXT")
    if doc.get("notes"):
        pdf.set_font(style="I")
        pdf.multi_cell(0, 6, doc["notes"], new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(style="")
    pdf.ln(4)

    widths = (28, 82, 18, 30, 32)
    heads = ("SKU", "Description", "Qty", "Unit price", "Amount")
    pdf.set_font(style="B")
    for w, h in zip(widths, heads):
        pdf.cell(w, 7, h, border="B")
    pdf.ln()
    pdf.set_font(style="")
    sign = -1 if doc["doc_type"] == "credit_note" else 1
    for ln in doc["lines"]:
        amount = str(Decimal(ln["unit_price"]) * ln["qty"] * sign)
        row = (ln["sku"], ln["description"][:44], str(ln["qty"]), fmt_money(ln["unit_price"], portal),
               fmt_money(amount, portal))
        for w, v in zip(widths, row):
            pdf.cell(w, 6, v)
        pdf.ln()
    pdf.ln(2)
    pdf.set_font(style="B")
    pdf.cell(sum(widths[:-1]), 7, "Total" if portal != "b" else "Gesamtbetrag / Total", align="R")
    pdf.cell(widths[-1], 7, fmt_money(doc["total"], portal), new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
