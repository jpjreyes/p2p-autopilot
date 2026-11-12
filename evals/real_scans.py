"""Reading real scans: the extraction model on SROIE (ICDAR 2019), 347 real scanned receipts with labeled fields.

Why: the portal invoices' scans are generated (D14). This measures the same model, backend and reading conventions
on real paper: thermal-printed receipts, photographed or scanned, faded, skewed, folded. Receipts are not invoices
(no PO, no item schema), so the fields scored are the ones both share and AP cares about most: the seller, the
date and the total (plus the address, SROIE's fourth field).

Data (not redistributed here): SROIE task 3 test split, via the Hugging Face copy `podbilabs/sroie-donut`:
    uv run --with huggingface_hub python -c "from huggingface_hub import snapshot_download as s; \
s('podbilabs/sroie-donut', repo_type='dataset', allow_patterns=['test/*'], local_dir='runs/real_scans/sroie')"

Run (resumable; each answer is saved as it arrives):
    uv run python evals/real_scans.py [--limit N] [--workers 4]
    uv run python evals/real_scans.py --score      # score what is saved so far
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from pathlib import Path

from PIL import Image

from p2p_autopilot import subscription
from p2p_autopilot.llm import get_backend

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "runs" / "real_scans" / "sroie" / "test"
OUT = ROOT / "runs" / "real_scans" / "results.jsonl"
SUMMARY = ROOT / "evals" / "real_scans_results.json"
MAX_SIDE = 1568  # the model works at this size anyway; larger images are only bigger requests

# Same conventions as the invoice extraction (extract.py): printed values only, the document's own date
# convention, money as plain decimals. Nothing here is specific to this dataset.
SYSTEM = """You extract fields from scanned receipts and invoices for accounts payable.
Return exactly what the document says; never compute or guess values that are not printed.
- company: the seller's name exactly as printed (usually at the top).
- address: the seller's address as printed, on one line.
- date: the document date as ISO YYYY-MM-DD. Read the date format from the document's conventions
  (US MM/DD/YYYY, European/Asian DD/MM/YYYY, or ISO).
- total: the final amount the customer pays, as a plain decimal string with a dot and no thousands
  separators: "1234.50". If the document shows rounding, the total is the amount after rounding."""

SCHEMA = {
    "type": "object",
    "properties": {"company": {"type": "string"}, "address": {"type": "string"},
                   "date": {"type": "string"}, "total": {"type": "string"}},
    "required": ["company", "address", "date", "total"],
}
PROMPT = ("The document is a scan with no text layer; its page image is attached. Read every field from the image. "
          "If a character is unreadable, give your best reading.")


def png(path: Path) -> bytes:
    img = Image.open(path)
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    return buf.getvalue()


def labels() -> dict[str, dict]:
    out = {}
    for line in (DATA / "metadata.jsonl").read_text().splitlines():
        m = json.loads(line)
        out[m["file_name"]] = json.loads(m["ground_truth"])["gt_parse"]
    return out


# ------------------------------------------------------------------ scoring

_DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%y", "%d %b %Y", "%d %B %Y",
                 "%d-%b-%Y", "%d %b %y", "%d-%b-%y", "%Y/%m/%d", "%d%b%Y", "%b %d, %Y", "%d.%m.%y",
                 "%d/%b/%Y", "%m/%d/%Y")  # last: a US date on a day-first receipt (e.g. 4/22/2018)


def label_date(s: str) -> str | None:
    """SROIE labels are printed strings (Malaysian receipts: day first). None if the label can't be parsed."""
    s = re.sub(r"\s+", " ", s.strip().upper()).replace("DATE:", "").strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s.title() if "%b" in fmt or "%B" in fmt else s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def money(s: str) -> Decimal | None:
    s = re.sub(r"[^\d.,-]", "", s or "")
    if s.count(",") and not s.count("."):
        s = s.replace(",", ".")
    s = s.replace(",", "")
    try:
        return Decimal(s).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def text(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def no_regno(s: str) -> str:
    """Malaysian receipts print the company registration number after the name, e.g. "(519537-X)"; SROIE's labels
    leave it out. Scored both ways: with it (strict) and without it."""
    return text(re.sub(r"\(?\b\d{5,7}-?[A-Z]\)?", "", (s or "").upper()))


def score(results: list[dict], gt: dict[str, dict]) -> dict:
    rows = []
    for r in results:
        g, p = gt[r["file"]], r["answer"]
        gd = label_date(g.get("date", ""))
        rows.append({
            "file": r["file"],
            "total": money(p["total"]) == money(g.get("total", "")) if money(g.get("total", "")) is not None else None,
            "date": (p["date"].strip() == gd) if gd else None,
            "company_exact": text(p["company"]) == text(g.get("company", "")),
            "company_fuzzy": SequenceMatcher(None, text(p["company"]), text(g.get("company", ""))).ratio() >= 0.9,
            "company_no_regno": no_regno(p["company"]) == no_regno(g.get("company", "")),
            "address_exact": text(p["address"]) == text(g.get("address", "")),
            "address_fuzzy": SequenceMatcher(None, text(p["address"]), text(g.get("address", ""))).ratio() >= 0.9,
        })

    def rate(key):
        vals = [x[key] for x in rows if x[key] is not None]
        return {"right": sum(vals), "scored": len(vals), "rate": round(sum(vals) / len(vals), 3) if vals else None}

    both = [x for x in rows if x["total"] is not None and x["date"] is not None]
    return {
        "documents": len(rows),
        "total": rate("total"), "date": rate("date"),
        "total_and_date": {"right": sum(x["total"] and x["date"] for x in both), "scored": len(both),
                           "rate": round(sum(x["total"] and x["date"] for x in both) / len(both), 3) if both else None},
        "company_exact": rate("company_exact"), "company_fuzzy_0.9": rate("company_fuzzy"),
        "company_without_registration_no": rate("company_no_regno"),
        "address_exact": rate("address_exact"), "address_fuzzy_0.9": rate("address_fuzzy"),
        "misses": [x["file"] for x in rows if x["total"] is False or x["date"] is False],
        "tokens_in": sum(r["tokens_in"] for r in results), "tokens_out": sum(r["tokens_out"] for r in results),
        "api_equivalent_usd": round(sum(r["cost_usd"] for r in results), 4),
    }


# ------------------------------------------------------------------ run

def load_done() -> list[dict]:
    return [json.loads(x) for x in OUT.read_text().splitlines()] if OUT.exists() else []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="only the first N documents (sorted by file name)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--score", action="store_true", help="only score the saved answers")
    args = ap.parse_args()
    gt = labels()
    if not args.score:
        files = sorted(gt)[: args.limit or None]
        done = {r["file"] for r in load_done()}
        todo = [f for f in files if f not in done]
        backend, lock, started = get_backend(), threading.Lock(), time.monotonic()
        print(f"{len(done)} already saved, {len(todo)} to read", flush=True)

        def read(f: str) -> dict:
            res = backend.complete(SYSTEM, PROMPT, SCHEMA, images=[png(DATA / f)])
            return {"file": f, "answer": res.data, "tokens_in": res.input_tokens, "tokens_out": res.output_tokens,
                    "latency_s": round(res.latency_s, 2), "cost_usd": res.cost_usd}

        OUT.parent.mkdir(parents=True, exist_ok=True)
        with ThreadPoolExecutor(args.workers) as pool:
            futures = {pool.submit(read, f): f for f in todo}
            for n, fut in enumerate(as_completed(futures), 1):
                try:
                    row = fut.result()
                except subscription.EvalStop:  # usage limit or unclean setup: saved answers stay, rerun resumes
                    pool.shutdown(cancel_futures=True)
                    raise
                except RuntimeError as e:  # one unreadable answer is one miss, not a dead run
                    row = {"file": futures[fut], "answer": {"company": "", "address": "", "date": "", "total": ""},
                           "tokens_in": 0, "tokens_out": 0, "latency_s": 0, "cost_usd": 0.0, "error": str(e)[:200]}
                with lock, OUT.open("a") as fh:
                    fh.write(json.dumps(row) + "\n")
                eta = (time.monotonic() - started) / n * (len(todo) - n)
                if n % 10 == 0 or n == len(todo):
                    use = subscription.last_limits or {}
                    print(f"{n}/{len(todo)} · ETA {int(eta // 60)} min · 5h "
                          f"{(use.get('five_hour') or {}).get('utilization')} · week "
                          f"{(use.get('seven_day') or {}).get('utilization')}", flush=True)
    results = [r for r in load_done() if r["file"] in gt]
    summary = score(results, gt)
    if not args.limit:
        SUMMARY.write_text(json.dumps(summary, indent=1))
    print(json.dumps({k: v for k, v in summary.items() if k != "misses"}, indent=1))
    print(f"{len(summary['misses'])} documents with a wrong total or date")


if __name__ == "__main__":
    try:
        main()
    except subscription.EvalStop as e:
        print(f"stopped: {e}", file=sys.stderr)
        sys.exit(75)
