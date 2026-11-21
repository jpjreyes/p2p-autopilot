"""Scanned invoices from P4's own generator, for the cascade test (DECISIONS D28/D30).

All 92 generated documents (portals A-D, four layouts, none used in training) rendered as the `scanned` chaos mode
serves them (grayscale, tilted, blurred, noisy, no text layer), first page as a JPEG capped at 1,568 px. Labels are
the generator's truth: supplier name, issue date, total. The portal row (date + amount) is the second source the
D8 check compares against.

    uv run python evals/finetune/invoices.py      # writes into runs/finetune/data/invoices/
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pypdfium2 as pdfium

from p2p_autopilot.portals.pdf import render, scanned

ROOT = Path(__file__).resolve().parents[2]
GEN = ROOT / "data" / "generated"
OUT = ROOT / "runs" / "finetune" / "data" / "invoices"
MAX_SIDE = 1568


def main() -> None:
    (OUT / "images").mkdir(parents=True, exist_ok=True)
    docs = json.loads((GEN / "documents.json").read_text())
    suppliers = {s["portal"]: s for s in json.loads((GEN / "suppliers.json").read_text())}
    rows = []
    for i, d in enumerate(docs, 1):
        pdf = scanned(render(d, suppliers[d["portal"]]), d["number"])
        img = pdfium.PdfDocument(io.BytesIO(pdf))[0].render(scale=1).to_pil().convert("RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        name = f"{d['doc_id']}.jpg"
        img.save(OUT / "images" / name, "JPEG", quality=90)
        rows.append({"file": name, "portal": d["portal"], "doc_type": d["doc_type"],
                     "gt": {"company": suppliers[d["portal"]]["name"], "date": d["issue_date"], "total": d["total"]},
                     "portal_row": {"date": d["issue_date"], "amount": d["total"]}})
        if i % 20 == 0:
            print(f"{i}/{len(docs)}", flush=True)
    (OUT / "invoices.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"{len(rows)} invoice scans -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
