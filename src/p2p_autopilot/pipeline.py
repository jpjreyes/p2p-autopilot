"""After an agent run: read every downloaded PDF, check it, 3-way match it, and produce review items for AP.

Nothing here approves or pays. Each review item says what the agent proposes (pay X, or why a human must look),
with the evidence. The same function scores the run against the ground truth, so evals reuse it.

Run:  uv run python -m p2p_autopilot.pipeline runs/<run-dir>
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

from p2p_autopilot import tracing
from p2p_autopilot.data.generate import generate
from p2p_autopilot.extract import Extraction, extract
from p2p_autopilot.llm import Backend, get_backend
from p2p_autopilot.matching import Ledger, match
from p2p_autopilot.orders.store import OrderSystem, PostgresOrderSystem, connect
from p2p_autopilot.process.risk import block_note

DATA = generate()
SUPPLIER_BY_PORTAL = {s["portal"]: s["id"] for s in DATA["suppliers"]}


@dataclass
class ReviewItem:
    number: str
    pdf: str
    status: str            # "proposed" (agent is confident) | "needs_human" | "no_action" (already paid)
    verdict: str           # match / price_above_po / ... / extraction_failed / portal_mismatch
    payable: str | None
    evidence: list[str]
    portal_check: str
    attempts: int
    extracted: dict = field(default_factory=dict)  # what the model read (printed values + handwriting), for review


def process(run_dir: str | Path, backend: Backend, orders: OrderSystem) -> list[ReviewItem]:
    with tracing.span("process_run", "CHAIN", **{"lpa.run_dir": Path(run_dir).name}) as s:
        items = _process(run_dir, backend, orders)
        s.set_attribute("lpa.documents", len(items))
        s.set_attribute("lpa.needs_human", sum(i.status == "needs_human" for i in items))
        return items


def _process(run_dir: str | Path, backend: Backend, orders: OrderSystem) -> list[ReviewItem]:
    run = json.loads((Path(run_dir) / "run.json").read_text())
    supplier = SUPPLIER_BY_PORTAL[run["portal"]]
    extractions: list[Extraction] = []
    for pdf in run["downloads"]:
        with tracing.span("document", "CHAIN", **{"lpa.pdf": Path(pdf).name}) as sp:
            try:
                ex = extract(pdf, supplier, backend, run.get("contexts", {}).get(pdf))
            except RuntimeError as e:  # one bad model call must never stop the batch: this document goes to a human
                ex = Extraction(pdf, None, {}, [f"extraction failed: {e}"], "unavailable")
            sp.set_attribute("lpa.source", ex.source)
            sp.set_attribute("lpa.attempts", ex.attempts)
            sp.set_attribute("lpa.portal_check", ex.portal_check)
            sp.set_attribute("lpa.needs_human", ex.needs_human)
        extractions.append(ex)
        tag = "ok " if not ex.needs_human else "HUM"
        print(f"  {tag} {Path(pdf).name:<22} {ex.source:<5} tries={ex.attempts} portal={ex.portal_check:<11} "
              f"{'; '.join(ex.errors + ex.portal_notes)[:90]}", flush=True)

    usage = {"calls": sum(e.attempts for e in extractions if e.tokens_in),
             "tokens_in": sum(e.tokens_in for e in extractions),
             "tokens_out": sum(e.tokens_out for e in extractions),
             "read_from_images": sum(e.source == "image" for e in extractions)}
    (Path(run_dir) / "extract_usage.json").write_text(json.dumps(usage))
    ledger, items = Ledger(), []
    # Work the queue in issue-date order, like a clerk: the first copy of a bill is the original.
    for ex in sorted(extractions, key=lambda e: (e.doc.issue_date, e.doc.number) if e.doc else ("9999", e.pdf)):
        if ex.doc is None:
            items.append(ReviewItem(Path(ex.pdf).stem, ex.pdf, "needs_human", "extraction_failed", None,
                                    ex.errors, ex.portal_check, ex.attempts, ex.raw))
            continue
        with tracing.span("match", "TOOL", **{"lpa.number": ex.doc.number, "lpa.po": ex.doc.po_number}) as sp:
            v = match(ex.doc, orders, ledger)
            sp.set_attribute("lpa.verdict", v.verdict)
            sp.set_attribute("lpa.payable", "" if v.payable is None else str(v.payable))
        note = block_note(ex.doc.po_number)  # predict -> act (D18c): evidence for the reviewer, never a verdict
        if note and v.verdict not in ("unknown_po", "already_paid", "credit_note"):
            v.evidence.append(note)
        if ex.portal_check == "disagree":
            items.append(ReviewItem(ex.doc.number, ex.pdf, "needs_human", "portal_mismatch", None,
                                    ex.portal_notes + v.evidence, ex.portal_check, ex.attempts, ex.raw))
            continue
        status = ("no_action" if v.verdict == "already_paid"
                  else "proposed" if v.payable is not None and v.verdict == "match" else "needs_human")
        if ex.raw.get("amount_changed_by_hand"):
            # The amount is in doubt: never pay the printed or the handwritten number automatically (D15).
            status = "needs_human" if status == "proposed" else status
            v.evidence.append("handwritten change on the document: " + "; ".join(ex.raw.get("handwritten_notes") or
                                                                              ["(not transcribed)"]))
        items.append(ReviewItem(ex.doc.number, ex.pdf, status, v.verdict,
                                None if v.payable is None else str(v.payable), v.evidence, ex.portal_check,
                                ex.attempts, ex.raw))
    (Path(run_dir) / "review.json").write_text(json.dumps([asdict(i) for i in items], indent=2))
    return items


def score(run_dir: str | Path, items: list[ReviewItem], must_review: set[str] = frozenset()) -> dict:
    """Compare review items with the ground truth for the documents that are open on this portal.
    must_review: numbers that must reach a human whatever the match says (e.g. handwritten amount changes)."""
    run = json.loads((Path(run_dir) / "run.json").read_text())
    truth = {t["number"]: t for t in DATA["ground_truth"] if t["portal"] == run["portal"] and t["in_scope"]}
    by_number = {i.number: i for i in items}
    verdict_ok = payable_ok = 0
    misses = []
    for number, t in truth.items():
        item = by_number.get(number)
        if item is None:
            misses.append(f"{number}: not processed")
            continue
        exp = None if t["expected_payable"] is None else Decimal(t["expected_payable"])
        got = None if item.payable is None else Decimal(item.payable)
        verdict_ok += item.verdict == t["verdict"]
        payable_ok += got == exp
        if item.verdict != t["verdict"] or got != exp:
            misses.append(f"{number}: got {item.verdict}/{got}, expected {t['verdict']}/{exp}")
    unsafe = [i.number for i in items if i.status == "proposed"
              and (i.number in must_review or i.number not in truth or truth[i.number]["verdict"] != "match"
                   or Decimal(i.payable) != Decimal(truth[i.number]["expected_payable"]))]
    return {"documents": len(truth), "processed": len(items), "verdict_correct": verdict_ok,
            "payable_correct": payable_ok, "needs_human": sum(i.status == "needs_human" for i in items),
            "unsafe_proposals": unsafe, "misses": misses}


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    args = ap.parse_args()
    with connect() as conn:
        items = process(args.run_dir, get_backend(), PostgresOrderSystem(conn))
    s = score(args.run_dir, items)
    print(json.dumps({k: v for k, v in s.items() if k != "misses"}, indent=2))
    for m in s["misses"]:
        print("  MISS", m)


if __name__ == "__main__":
    main()
