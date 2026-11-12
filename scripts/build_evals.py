"""Summarize every saved eval run (runs/chaos-*.json) into web/public/evals.json for the console's Evals page.

The page shows measured results only: per portal, failure mode and variant, the latest run (current code) and the
history (including runs from before the fixes recorded in DECISIONS.md).
Run after an eval:  uv run python scripts/build_evals.py
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "public" / "evals.json"


def main() -> None:
    rows = []
    # development runs by timestamp, then the final evals (runs/final, D23-D25) in the order they ran
    final = sorted((ROOT / "runs" / "final").glob("*.json"), key=lambda f: f.stat().st_mtime)
    for f in sorted((ROOT / "runs").glob("chaos-*.json")) + final:
        for r in json.loads(f.read_text()):
            r.setdefault("variant", "full")
            r["file"] = f.name
            rows.append(r)
    cells: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for r in rows:
        cells[(r["variant"], r["portal"], r["mode"])].append(r)

    def cell(group: list[dict]) -> dict:
        scored = [r for r in group if "verdict_correct" in r]
        last = group[-1]  # files sort by timestamp: the last run is the current code
        return {
            "latest_pass": bool(last["pass"]),
            "latest_side_effects": last.get("side_effects", 0),
            "latest_docs_right": f"{last['verdict_correct']}/{last.get('documents', 20)}" if "verdict_correct" in last else None,
            "runs": len(group),
            "passed": sum(bool(r["pass"]) for r in group),
            "unsafe": sum(r.get("unsafe", 0) for r in group),
            "side_effects": sum(r.get("side_effects", 0) for r in group),
            "calls_median": sorted(r["calls"] for r in group)[len(group) // 2],
            "seconds_median": sorted(float(r["seconds"]) for r in group)[len(group) // 2],
            "docs_right": f"{min((r['verdict_correct'] for r in scored), default=0)}/{scored[0].get('documents', 20)}" if scored else None,
            "nav_usd": round(sum(r.get("nav_usd", 0) for r in group) / len(group), 4) if any(
                "nav_usd" in r for r in group) else None,
            "hw_caught": (f"{sum(r['hw_caught'] for r in group)}/{sum(r['hw_corrections'] for r in group)}"
                          if any("hw_corrections" in r for r in group) else None),
        }

    out = {
        "generated_at": datetime.now().isoformat(timespec="minutes"),
        "totals": {
            "runs": len(rows),
            "unsafe": sum(r.get("unsafe", 0) for r in rows),
            "side_effects_full": sum(r.get("side_effects", 0) for r in rows if r["variant"] == "full"),
        },
        "cells": [{"variant": v, "portal": p, "mode": m, **cell(g)} for (v, p, m), g in sorted(cells.items())],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1))
    print(f"{len(rows)} runs, {len(cells)} cells -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
