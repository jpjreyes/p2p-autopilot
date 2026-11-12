"""Handwriting on invoices (D15): planted deterministically, read from the scan, and a handwritten amount change always
reaches a human, whatever the 3-way match says."""

import io
import json
from collections import Counter

from pypdf import PdfReader

from p2p_autopilot.extract import pdf_text
from p2p_autopilot.llm import LLMResult
from p2p_autopilot.pipeline import process, score
from p2p_autopilot.portals import handwriting as hw
from p2p_autopilot.portals.app import DOCS, SUPPLIERS
from p2p_autopilot.portals.pdf import fmt_money, render, scanned
from test_matching import DATA, MemoryOrderSystem


def test_plan_is_deterministic_and_never_corrects_a_credit_note():
    plans = [hw.plan(d["number"], d["doc_type"]) for p in "abc" for d in DOCS[p] if d["status"] == "open"]
    assert plans == [hw.plan(d["number"], d["doc_type"]) for p in "abc" for d in DOCS[p] if d["status"] == "open"]
    assert 5 <= Counter(plans)["amount_correction"] <= 25
    assert all(hw.plan(d["number"], d["doc_type"]) != "amount_correction"
               for p in "abc" for d in DOCS[p] if d["doc_type"] == "credit_note")


def test_handwritten_page_is_a_scan_without_text():
    d = next(x for x in DOCS["a"] if hw.plan(x["number"], x["doc_type"]) == "amount_correction")
    body = render(d, SUPPLIERS["a"])
    pdf = scanned(body, d["number"], hw.annotate(body, d, fmt_money(d["total"], "a")))
    assert "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages).strip() == ""


class Fake:
    def __init__(self, raw):
        self.raw = raw

    def complete(self, system, prompt, schema, model="haiku", images=None):
        return LLMResult(self.raw, 1, 1, 0.0, model)


def test_handwritten_amount_change_is_never_proposed(tmp_path, monkeypatch):
    monkeypatch.setenv("LPA_NO_EXTRACT_CACHE", "1")
    truth = {t["doc_id"]: t for t in DATA["ground_truth"]}
    d = next(x for x in DOCS["a"] if x["status"] == "open" and truth[x["doc_id"]]["verdict"] == "match")
    pdf = tmp_path / f"{d['number']}.pdf"
    pdf.write_bytes(render(d, SUPPLIERS["a"]))
    assert pdf_text(pdf)
    (tmp_path / "run.json").write_text(json.dumps({"portal": "a", "downloads": [str(pdf)], "contexts": {}}))
    raw = {"doc_type": "invoice", "number": d["number"], "po_number": d["po_number"], "issue_date": d["issue_date"],
           "due_date": d["due_date"], "total": d["total"],
           "lines": [{"sku": ln["sku"], "qty": ln["qty"], "unit_price": ln["unit_price"]} for ln in d["lines"]]}
    clean = process(tmp_path, Fake({**raw, "amount_changed_by_hand": False}), MemoryOrderSystem(DATA))
    assert clean[0].status == "proposed"  # control: the same invoice without ink is a match
    items = process(tmp_path, Fake({**raw, "amount_changed_by_hand": True, "handwritten_notes": ["1,900.00 per Dana"]}),
                    MemoryOrderSystem(DATA))
    assert items[0].status == "needs_human" and "1,900.00 per Dana" in " ".join(items[0].evidence)
    # and if it had been proposed, scoring would count it as unsafe
    assert score(tmp_path, clean, {d["number"]})["unsafe_proposals"] == [d["number"]]
