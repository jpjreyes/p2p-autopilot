"""The cascade, measured (DECISIONS D30): the fine-tuned small model reads first; code checks decide whether its
answer stands; Claude (Haiku) reads only what the checks reject.

Checks, by what the document offers:
  - SROIE receipts (real paper, no second source): the answer parses, the date is a real ISO date in a plausible
    range, the total is a positive amount, the seller is not empty. Weak by design: a well-formed misread passes.
  - Generated invoices (P4's D8 rule): the date and the total must equal the portal row's date and amount.
Reported per set: how often Claude is needed, final accuracy, small-model-alone and Claude-alone accuracy, and
silent errors (a wrong answer the checks let through).

    uv run python evals/finetune/cascade.py --run runs/finetune/kaggle_out
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "evals"))
from real_scans import money, no_regno  # noqa: E402
from score import DATA, HAIKU, judge, labels, load  # noqa: E402

INV = DATA / "invoices" / "invoices.jsonl"
HAIKU_INV = ROOT / "runs" / "finetune" / "haiku_inv.jsonl"


def iso_ok(s: str) -> bool:
    try:
        return date(2000, 1, 1) <= date.fromisoformat(s.strip()) <= date(2026, 12, 31)
    except (ValueError, AttributeError):
        return False


def receipt_check(a: dict | None) -> bool:
    if not isinstance(a, dict):
        return False
    t = money(str(a.get("total") or ""))
    return iso_ok(str(a.get("date") or "")) and t is not None and t > 0 and bool(str(a.get("company") or "").strip())


def invoice_check(a: dict | None, row: dict) -> bool:
    if not isinstance(a, dict):
        return False
    return str(a.get("date") or "").strip() == row["date"] and money(str(a.get("total") or "")) == money(row["amount"])


def invoice_judge(a: dict | None, g: dict) -> dict:
    a = a if isinstance(a, dict) else {}
    d = str(a.get("date") or "").strip() == g["date"]
    t = money(str(a.get("total") or "")) == money(g["total"])
    return {"total": t, "date": d, "total_and_date": t and d,
            "company": no_regno(str(a.get("company") or "")) == no_regno(g["company"])}


def run_set(name, files, small, large, check, correct, haiku_cost):
    n = len(files)
    esc = [f for f in files if not check(f, small.get(f))]
    final = {f: (large.get(f) if f in esc else small.get(f)) for f in files}
    ok = lambda ans, f: correct(ans, f)
    silent = [f for f in files if f not in esc and not ok(small.get(f), f)]
    return {
        "set": name, "n": n,
        "escalated_to_claude": round(len(esc) / n, 3),
        "accuracy_total_and_date": {"small_alone": round(sum(ok(small.get(f), f) for f in files) / n, 3),
                                    "claude_alone": round(sum(ok(large.get(f), f) for f in files) / n, 3),
                                    "cascade": round(sum(ok(final[f], f) for f in files) / n, 3)},
        "silent_errors": len(silent), "silent_error_files": silent,
        "claude_cost_per_1000_docs_usd": round(1000 * haiku_cost * len(esc) / n, 2),
        "claude_alone_cost_per_1000_docs_usd": round(1000 * haiku_cost, 2),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, required=True)
    a = ap.parse_args()
    out = {}

    gt = labels("test")
    haiku = load(HAIKU)
    hc = [json.loads(x).get("cost_usd", 0) for x in HAIKU.read_text().splitlines()]
    small = load(a.run / "preds_ft_test.jsonl")
    out["sroie_test"] = run_set("SROIE test (real paper)", sorted(gt), small, haiku,
                                lambda f, ans: receipt_check(ans), lambda ans, f: judge(ans, gt[f])["total_and_date"],
                                sum(hc) / len(hc))
    unseen = json.loads((DATA / "splits.json").read_text())["test_unseen_company"]
    out["sroie_unseen"] = run_set("SROIE test, unseen companies", sorted(unseen), small, haiku,
                                  lambda f, ans: receipt_check(ans), lambda ans, f: judge(ans, gt[f])["total_and_date"],
                                  sum(hc) / len(hc))

    if HAIKU_INV.exists() and (a.run / "preds_ft_inv.jsonl").exists():
        inv = {r["file"]: r for r in map(json.loads, INV.read_text().splitlines())}
        hrows = [json.loads(x) for x in HAIKU_INV.read_text().splitlines()]
        h_inv = {r["file"]: r.get("answer") for r in hrows}
        s_inv = {k.split("/")[-1]: v for k, v in load(a.run / "preds_ft_inv.jsonl").items()}
        b_inv = {k.split("/")[-1]: v for k, v in load(a.run / "preds_base_inv.jsonl").items()}
        cost = sum(r.get("cost_usd", 0) for r in hrows) / max(1, len(hrows))
        files = sorted(inv)
        out["invoices"] = run_set("Generated invoice scans (D8 check vs portal row)", files, s_inv, h_inv,
                                  lambda f, ans: invoice_check(ans, inv[f]["portal_row"]),
                                  lambda ans, f: invoice_judge(ans, inv[f]["gt"])["total_and_date"], cost)
        out["invoices_untuned_small_model"] = run_set(
            "Generated invoice scans, untuned small model first", files, b_inv, h_inv,
            lambda f, ans: invoice_check(ans, inv[f]["portal_row"]),
            lambda ans, f: invoice_judge(ans, inv[f]["gt"])["total_and_date"], cost)

    path = ROOT / "evals" / "finetune" / "results_cascade.json"
    path.write_text(json.dumps(out, indent=1))
    for k, v in out.items():
        acc = v["accuracy_total_and_date"]
        print(f"{v['set']:52s} n={v['n']:3d} | to Claude {v['escalated_to_claude']:.1%} | small {acc['small_alone']:.3f}"
              f" claude {acc['claude_alone']:.3f} cascade {acc['cascade']:.3f} | silent errors {v['silent_errors']}")
    print(f"saved {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
