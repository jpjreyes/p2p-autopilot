"""Score receipt readers on SROIE (DECISIONS D28): untuned Qwen3-VL-4B, fine-tuned, and Haiku (D26 answers).

    uv run python evals/finetune/score.py --run runs/finetune/kaggle_out [--split test|val]

Test is scored once per model (D28); `--split val` is the held-out 50 used by the registry gate.
Each model is reported on all receipts and, for test, on the 100 from companies never seen in training.
Totals two ways: strict (equals the label) and adjusted (label, or label rounded to 0.05 = Malaysian cash rounding).
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import ROUND_HALF_UP, Decimal
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "evals"))
from real_scans import label_date, money, no_regno, text  # noqa: E402

DATA = ROOT / "runs" / "finetune" / "data"
HAIKU = ROOT / "runs" / "real_scans" / "results.jsonl"
FIVE_CENTS = Decimal("0.05")


def cash_round(x: Decimal) -> Decimal:
    return ((x / FIVE_CENTS).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * FIVE_CENTS).quantize(Decimal("0.01"))


def load(path: Path) -> dict[str, dict | None]:
    return {r["file"]: r.get("answer") for r in map(json.loads, path.read_text().splitlines())} if path.exists() else {}


def labels(split: str) -> dict[str, dict]:
    key = "gt" if split == "test" else "target"
    return {r["file"]: r[key] for r in map(json.loads, (DATA / f"{split}.jsonl").read_text().splitlines())}


def judge(p: dict | None, g: dict) -> dict:
    p = p if isinstance(p, dict) else {}
    get = lambda k: str(p.get(k) or "")
    gt_total, pred_total, gd = money(g.get("total", "")), money(get("total")), label_date(g.get("date", ""))
    strict = pred_total is not None and pred_total == gt_total
    adjusted = strict or (pred_total is not None and gt_total is not None and pred_total == cash_round(gt_total))
    date = gd is not None and get("date").strip() == gd
    return {
        "parsed": bool(p), "total_strict": strict, "total_adjusted": adjusted, "date": date,
        "total_and_date": adjusted and date,
        "company": no_regno(get("company")) == no_regno(g.get("company", "")),
        "address_fuzzy": SequenceMatcher(None, text(get("address")), text(g.get("address", ""))).ratio() >= 0.9,
    }


def summarize(preds: dict, gt: dict, files: list[str]) -> dict:
    rows = [judge(preds.get(f), gt[f]) for f in files]
    n = len(rows)
    out = {"n": n, "missing": sum(f not in preds for f in files)}
    for k in rows[0] if rows else []:
        out[k] = round(sum(r[k] for r in rows) / n, 3)
    out["misses"] = [f for f, r in zip(files, rows) if not r["total_and_date"]]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, required=True, help="folder with preds_*.jsonl from the Kaggle job")
    ap.add_argument("--split", choices=["test", "val"], default="test")
    a = ap.parse_args()

    gt = labels(a.split)
    models = {"qwen3vl4b_untuned": load(a.run / f"preds_base_{a.split}.jsonl"),
              "qwen3vl4b_finetuned": load(a.run / f"preds_ft_{a.split}.jsonl")}
    if a.split == "test":
        models["haiku_d26"] = load(HAIKU)
    subsets = {"all": sorted(gt)}
    if a.split == "test":
        subsets["unseen_company"] = sorted(json.loads((DATA / "splits.json").read_text())["test_unseen_company"])

    result = {m: {s: summarize(p, gt, fs) for s, fs in subsets.items()} for m, p in models.items() if p}
    out = ROOT / "evals" / "finetune" / f"results_{a.split}.json"
    out.write_text(json.dumps(result, indent=1))

    cols = ["total_strict", "total_adjusted", "date", "total_and_date", "company", "address_fuzzy", "parsed"]
    for s in subsets:
        print(f"\n{a.split} / {s}")
        print(f"{'model':22s} " + " ".join(f"{c[:14]:>14s}" for c in cols))
        for m, r in result.items():
            print(f"{m:22s} " + " ".join(f"{r[s][c]:>14.3f}" for c in cols) + f"   n={r[s]['n']} missing={r[s]['missing']}")
    print(f"\nsaved {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
