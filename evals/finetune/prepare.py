"""Build the private Kaggle dataset for fine-tuning the receipt reader (DECISIONS D28).

Inputs: the SROIE copy used in D26 (`podbilabs/sroie-donut`, train + test splits) under runs/real_scans/sroie.
Outputs (runs/finetune/data, uploaded as a PRIVATE Kaggle dataset; SROIE is never published from this repo):
    images/<file>.jpg      every train and test scan, long side capped at 1,568 px (the size Haiku read in D26)
    train.jsonl            training examples: file + target JSON (company, address, date as ISO, total)
    val.jsonl              50 training receipts held out for checking progress during training
    test.jsonl             the 347 test receipts with their labels (scored once per model, see D28)
    splits.json            which test files belong to a company never seen in training ("unseen companies")

Run:  uv run python evals/finetune/prepare.py
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "evals"))
from real_scans import label_date, no_regno  # noqa: E402  (same label conventions as D26)

SRC = ROOT / "runs" / "real_scans" / "sroie"
OUT = ROOT / "runs" / "finetune" / "data"
MAX_SIDE = 1568
VAL_SIZE = 50
SEED = 516


def read_split(name: str) -> list[dict]:
    rows = []
    for line in (SRC / name / "metadata.jsonl").read_text().splitlines():
        m = json.loads(line)
        rows.append({"file": m["file_name"], "gt": json.loads(m["ground_truth"])["gt_parse"]})
    return rows


def target(gt: dict) -> dict | None:
    """The answer the model learns to give. Date as ISO (the extraction's convention); None if unparseable."""
    iso = label_date(gt.get("date", ""))
    if not iso or not gt.get("total"):
        return None
    return {"company": gt.get("company", ""), "address": gt.get("address", ""), "date": iso, "total": gt["total"]}


def save_image(split: str, file: str) -> None:
    dst = OUT / "images" / file
    if dst.exists():
        return
    img = Image.open(SRC / split / file).convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    img.save(dst, "JPEG", quality=90)


def main() -> None:
    (OUT / "images").mkdir(parents=True, exist_ok=True)
    train_rows, test_rows = read_split("train"), read_split("test")

    usable, dropped = [], []
    for r in train_rows:
        t = target(r["gt"])
        (usable if t else dropped).append({**r, "target": t})
    random.Random(SEED).shuffle(usable)
    val, train = usable[:VAL_SIZE], usable[VAL_SIZE:]

    seen = {no_regno(r["gt"].get("company", "")) for r in train_rows}
    unseen = [r["file"] for r in test_rows if no_regno(r["gt"].get("company", "")) not in seen]

    for i, r in enumerate(train_rows + test_rows, 1):
        save_image("train" if r in train_rows else "test", r["file"])
        if i % 100 == 0:
            print(f"images {i}/{len(train_rows) + len(test_rows)}", flush=True)

    def dump(name, rows, key):
        with open(OUT / name, "w") as f:
            for r in rows:
                f.write(json.dumps({"file": r["file"], key: r["target"] if key == "target" else r["gt"]}) + "\n")

    dump("train.jsonl", train, "target")
    dump("val.jsonl", val, "target")
    dump("test.jsonl", test_rows, "gt")
    (OUT / "splits.json").write_text(json.dumps({
        "train": len(train), "val": len(val), "dropped_unparseable_label": [r["file"] for r in dropped],
        "test": len(test_rows), "test_unseen_company": unseen, "seed": SEED, "max_side": MAX_SIDE,
    }, indent=1))
    print(f"train {len(train)}, val {len(val)}, dropped {len(dropped)}, test {len(test_rows)}, "
          f"unseen-company test {len(unseen)}")


if __name__ == "__main__":
    main()
