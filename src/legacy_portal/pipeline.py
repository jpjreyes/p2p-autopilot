"""After an agent run: read every downloaded PDF, check it, 3-way match it, and produce review items for AP.

Nothing here approves or pays. Each review item says what the agent proposes (pay X, or why a human must look),
with the evidence. The same function scores the run against the ground truth, so evals reuse it.

Run:  uv run python -m legacy_portal.pipeline runs/<run-dir>
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

from legacy_portal.data.generate import generate
from legacy_portal.extract import Extraction, extract
from legacy_portal.llm import Backend, get_backend
from legacy_portal.matching import Ledger, match
from legacy_portal.orders.store import OrderSystem, PostgresOrderSystem, connect

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


def process(run_dir: str | Path, backend: Backend, orders: OrderSystem) -> list[ReviewItem]:
    run = json.loads((Path(run_dir) / "run.json").read_text())
    supplier = SUPPLIER_BY_PORTAL[run["portal"]]
    extractions: list[Extraction] = []
    for pdf in run["downloads"]:
        try:
            ex = extract(pdf, supplier, backend, run.get("contexts", {}).get(pdf))
        except RuntimeError as e:  # one bad model call must never stop the batch: this document goes to a human
            ex = Extraction(pdf, None, {}, [f"extraction failed: {e}"], "unavailable")
        extractions.append(ex)
        tag = "ok " if not ex.needs_human else "HUM"
        print(f"  {tag} {Path(pdf).name:<22} tries={ex.attempts} portal={ex.portal_check:<11} "
              f"{'; '.join(ex.errors + ex.portal_notes)[:90]}", flush=True)

    usage = {"calls": sum(e.attempts for e in extractions if e.tokens_in),
             "tokens_in": sum(e.tokens_in for e in extractions),
             "tokens_out": sum(e.tokens_out for e in extractions)}
    (Path(run_dir) / "extract_usage.json").write_text(json.dumps(usage))
    ledger, items = Ledger(), []
    # Work the queue in issue-date order, like a clerk: the first copy of a bill is the original.
    for ex in sorted(extractions, key=lambda e: (e.doc.issue_date, e.doc.number) if e.doc else ("9999", e.pdf)):
        if ex.doc is None:
            items.append(ReviewItem(Path(ex.pdf).stem, ex.pdf, "needs_human", "extraction_failed", None,
                                    ex.errors, ex.portal_check, ex.attempts))
            continue
        v = match(ex.doc, orders, ledger)
        if ex.portal_check == "disagree":
            items.append(ReviewItem(ex.doc.number, ex.pdf, "needs_human", "portal_mismatch", None,
                                    ex.portal_notes + v.evidence, ex.portal_check, ex.attempts))
            continue
        status = ("no_action" if v.verdict == "already_paid"
                  else "proposed" if v.payable is not None and v.verdict == "match" else "needs_human")
        items.append(ReviewItem(ex.doc.number, ex.pdf, status, v.verdict,
                                None if v.payable is None else str(v.payable), v.evidence, ex.portal_check,
                                ex.attempts))
    (Path(run_dir) / "review.json").write_text(json.dumps([asdict(i) for i in items], indent=2))
    return items


def score(run_dir: str | Path, items: list[ReviewItem]) -> dict:
    """Compare review items with the ground truth for the documents that are open on this portal."""
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
              and (i.number not in truth or truth[i.number]["verdict"] != "match"
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
