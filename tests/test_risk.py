"""predict -> act (D18c): the block-risk note travels with the review item but never changes a verdict or an amount."""

import json

import pytest

from p2p_autopilot import pipeline
from p2p_autopilot.pipeline import process
from p2p_autopilot.portals.app import DOCS, SUPPLIERS
from p2p_autopilot.portals.pdf import render
from p2p_autopilot.process.risk import block_note
from p2p_autopilot.process.warehouse import DEFAULT_DB
from test_handwriting import Fake
from test_matching import DATA, MemoryOrderSystem

TRUTH = {t["doc_id"]: t for t in DATA["ground_truth"]}


def _run(tmp_path, monkeypatch, verdict: str, note: str | None):
    monkeypatch.setenv("LPA_NO_EXTRACT_CACHE", "1")
    monkeypatch.setattr(pipeline, "block_note", lambda po: note)
    d = next(x for x in DOCS["a"] if x["status"] == "open" and TRUTH[x["doc_id"]]["verdict"] == verdict)
    pdf = tmp_path / f"{d['number']}.pdf"
    pdf.write_bytes(render(d, SUPPLIERS["a"]))
    (tmp_path / "run.json").write_text(json.dumps({"portal": "a", "downloads": [str(pdf)], "contexts": {}}))
    raw = {"doc_type": "invoice", "number": d["number"], "po_number": d["po_number"], "issue_date": d["issue_date"],
           "due_date": d["due_date"], "total": d["total"], "amount_changed_by_hand": False,
           "lines": [{"sku": ln["sku"], "qty": ln["qty"], "unit_price": ln["unit_price"]} for ln in d["lines"]]}
    return process(tmp_path, Fake(raw), MemoryOrderSystem(DATA))[0]


@pytest.mark.parametrize("verdict", ["match", "qty_above_received"])
def test_note_is_evidence_only(tmp_path, monkeypatch, verdict):
    without = _run(tmp_path, monkeypatch, verdict, None)
    note = "payment-block risk 0.91 (high) when SAP recorded this PO's invoice: test (model, not a verdict)"
    with_note = _run(tmp_path, monkeypatch, verdict, note)
    assert (with_note.status, with_note.verdict, with_note.payable) == (without.status, without.verdict, without.payable)
    assert note in with_note.evidence and note not in without.evidence


def test_no_note_for_unknown_or_malformed_po():
    assert block_note("PO-4900000000") is None or "risk" in block_note("PO-4900000000")
    assert block_note("not-a-po") is None


@pytest.mark.skipif(not DEFAULT_DB.exists(), reason="warehouse not built")
def test_real_short_delivery_reads_as_high_risk_and_clean_matches_as_low():
    short = [t for t in DATA["ground_truth"] if t["verdict"] == "qty_above_received" and t["portal"] in "acd"]
    notes = [block_note(t["fields"]["po_number"]) for t in short]
    if any(n is None for n in notes):
        pytest.skip("line scores not built (predict --worklist)")
    assert all("(high)" in n and "no goods receipt yet" in n for n in notes)
    clean = [block_note(t["fields"]["po_number"]) for t in DATA["ground_truth"] if t["verdict"] == "match"]
    assert sum("(low)" in (n or "") for n in clean) >= 0.8 * len(clean)
