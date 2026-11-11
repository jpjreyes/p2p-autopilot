"""Predict, from the real SAP log, which invoices will be blocked for payment (D18). Classic ML, not an LLM.

Question: when an invoice is recorded for a PO line, will someone have to remove a payment block on it within 60 days?
(55,839 of 251,734 lines in BPI 2019 get a "Remove Payment Block"; the block itself is set silently by SAP when the
invoice posts, so the removal is the observable outcome. A blocked invoice waits a median of ~6 days for a person.)
If AP knew at invoice receipt, the buyer or the warehouse could fix the cause (missing goods receipt, price or quantity
difference) before the block, instead of after.

Leak-free by construction:
  - features use only events strictly before the decision point (two decision points: at PO creation = earliest
    warning, at invoice receipt = most information)
  - vendor history comes from months whose outcomes were already known: the vendor's block rate on invoices recorded
    3+ months before the decision point's month (a 60-day outcome is complete by then)
  - temporal split by invoice date: train < 2018-07-01; July 2018 = early stopping, calibration and threshold;
    August 2018 = development set (every modeling choice is compared here); test 2018-09-01 .. 2018-11-19 (the last
    day whose 60-day outcome is inside the data), scored only with --final.

Baselines: the base rate; a rule ("the invoice arrived before any goods receipt"); the vendor's past block rate alone.
Reported: ROC AUC, average precision, Brier score after calibration, and the operating point AP would use: how many of
the blocks are caught when 80% of the flags are right.

Run:  uv run python -m legacy_portal.process.predict          (after the warehouse; ~1-2 min)
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import duckdb
import lightgbm as lgb
import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from legacy_portal.process.warehouse import DEFAULT_DB, ROOT

RUNS = ROOT / "runs"
MODELS = ROOT / "data" / "models"
HORIZON_DAYS = 60
TRAIN_END, CALIB_END, VALID_END, TEST_END = "2018-07-01", "2018-08-01", "2018-09-01", "2018-11-19"
CATEGORICAL = ["item_category", "item_type", "document_type", "spend_area", "sub_spend_area", "company", "ir_user"]
# events whose count before the decision point is a feature
PRIOR = {"Change Price": "n_change_price", "Change Quantity": "n_change_qty", "Record Goods Receipt": "n_gr",
         "Receive Order Confirmation": "n_order_conf", "Cancel Goods Receipt": "n_cancel_gr",
         "Create Purchase Requisition Item": "has_requisition", "Vendor creates invoice": "n_vendor_invoice",
         "Change Approval for Purchase Order": "n_change_approval", "Record Service Entry Sheet": "n_service_entry"}
REASONS = {  # feature -> how a person reads it (for the worklist's "why")
    "invoice_before_gr": "invoice arrived before any goods receipt",
    "gr_based_inv_verif": "goods-receipt-based invoice check is on",
    "vendor_block_rate": "this vendor's invoices were often blocked before",
    "vendor_lines": "vendor volume",
    "log_value": "line value",
    "days_po_to_cut": "time since the order",
    "n_gr": "number of goods receipts so far",
    "n_change_price": "price changed on the order",
    "n_change_qty": "quantity changed on the order",
    "po_lines": "lines on the same order",
    "po_blocked_before": "other lines of this order were already blocked",
    "value_ratio": "invoiced amount differs from the order",
    "days_since_gr": "time since the goods arrived",
    "vendor_rpb_30d": "this vendor's invoices were blocked in the last 30 days",
    "vendor_ir_30d": "this vendor's recent invoice volume",
    "vendor_recent_block_ratio": "this vendor's recent block removals per invoice",
    "inv_lines": "lines on the same invoice",
    "inv_any_no_gr": "another line on this invoice has no goods receipt yet",
    "inv_share_no_gr": "share of this invoice's lines without goods receipt",
    "inv_log_value": "invoice total",
    "inv_any_price_change": "a line on this invoice had a price change",
    "inv_any_qty_change": "a line on this invoice had a quantity change",
    "ir_user": "recorded by", "ir_dow": "weekday recorded", "ir_day": "day of month recorded",
    "item_category": "match type", "item_type": "item type", "document_type": "document type",
    "spend_area": "spend area", "sub_spend_area": "sub spend area", "company": "company",
}


def build_frame(con: duckdb.DuckDBPyConnection, checkpoint: str, until: str = TEST_END,
                target: str = "block") -> dict[str, np.ndarray]:
    """target: "block" = any payment block removed within 60 days; "human" = removed by a person (not a batch job:
    29% of removals are SAP releasing the block automatically within a day of the goods arriving, D18)."""
    """One row per PO line that received an invoice; features as of the checkpoint ('po' or 'invoice')."""
    cut = "po_ts" if checkpoint == "po" else "ir_ts"
    prior = ",\n".join(f"count(*) FILTER (WHERE e.activity = '{a}') AS {c}" for a, c in PRIOR.items())
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE lines AS
        WITH f AS (
            SELECT case_id,
                   min(ts) FILTER (WHERE activity = 'Create Purchase Order Item') AS po_ts,
                   min(ts) FILTER (WHERE activity = 'Record Invoice Receipt')     AS ir_ts,
                   arg_min(user_id, ts) FILTER (WHERE activity = 'Record Invoice Receipt') AS ir_user
            FROM events WHERE is_canonical AND ts_status IN ('ok', 'repaired') GROUP BY 1)
        SELECT c.*, f.po_ts, f.ir_ts, f.ir_user,
               EXISTS (SELECT 1 FROM events e WHERE e.case_id = c.case_id AND e.is_canonical
                       AND e.activity = 'Remove Payment Block' AND e.ts > f.ir_ts
                       AND e.ts <= f.ir_ts + INTERVAL {HORIZON_DAYS} DAY
                       {"AND NOT starts_with(coalesce(e.user_id, ''), 'batch')" if target == "human" else ""})
                                                                             AS label,
               date_trunc('month', f.ir_ts)                                  AS ir_month,
               date_trunc('month', f.{cut})                                  AS cut_month
        FROM cases c JOIN f USING (case_id)
        WHERE f.ir_ts IS NOT NULL AND f.po_ts IS NOT NULL AND f.ir_ts < TIMESTAMP '{until}'
    """)
    # vendor history, lagged 3 months so every outcome counted was already known (no leakage)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE vendor_hist AS
        WITH m AS (SELECT vendor, ir_month, count(*) AS n, sum(label::INT) AS blocked FROM lines GROUP BY 1, 2),
        grid AS (SELECT DISTINCT l.vendor, l.cut_month AS at_month FROM lines l)
        SELECT g.vendor, g.at_month,
               coalesce(sum(m.n), 0) AS vendor_lines, coalesce(sum(m.blocked), 0) AS vendor_blocked
        FROM grid g LEFT JOIN m ON m.vendor = g.vendor AND m.ir_month <= g.at_month - INTERVAL 3 MONTH
        GROUP BY 1, 2
    """)
    global_rate = con.execute("SELECT avg(label::INT) FROM lines WHERE ir_ts < ?", [TRAIN_END]).fetchone()[0]
    # SAP blocks whole invoice documents: lines recorded together (same vendor, same second) share their fate (97.9%
    # of multi-line invoices agree in training), so each line sees its invoice's other lines, as known on arrival.
    if checkpoint == "invoice":
        inv = """count(*) OVER inv AS inv_lines, max(ev.no_gr_yet::INT) OVER inv AS inv_any_no_gr,
                 avg(ev.no_gr_yet::INT) OVER inv AS inv_share_no_gr,
                 ln(1 + sum(greatest(l.value_eur, 0)) OVER inv) AS inv_log_value,
                 max((ev.n_change_price > 0)::INT) OVER inv AS inv_any_price_change,
                 max((ev.n_change_qty > 0)::INT) OVER inv AS inv_any_qty_change,
                 coalesce(l.ir_user, 'NA') AS ir_user, dayofweek(l.ir_ts) AS ir_dow, day(l.ir_ts) AS ir_day"""
    else:  # at PO creation none of this exists yet
        inv = """NULL::INT AS inv_lines, NULL::INT AS inv_any_no_gr, NULL::DOUBLE AS inv_share_no_gr,
                 NULL::DOUBLE AS inv_log_value, NULL::INT AS inv_any_price_change, NULL::INT AS inv_any_qty_change,
                 'NA' AS ir_user, NULL::INT AS ir_dow, NULL::INT AS ir_day"""
    rows = con.execute(f"""
        WITH ev AS (
            SELECT l.case_id, {prior},
                   count(*) FILTER (WHERE e.activity = 'Record Goods Receipt') = 0 AS no_gr_yet,
                   max(e.ts) FILTER (WHERE e.activity = 'Record Goods Receipt') AS last_gr,
                   arg_max(e.value_eur, e.ts) AS value_now
            FROM lines l LEFT JOIN events e ON e.case_id = l.case_id AND e.is_canonical AND e.ts <= l.{cut}
                AND (e.ts < l.{cut} OR e.activity = 'Record Invoice Receipt')
            GROUP BY 1),
        vday AS (  -- the vendor's recent activity: blocks removed and invoices recorded per day (observed events)
            SELECT c.vendor, CAST(e.ts AS DATE) AS day,
                   count(*) FILTER (WHERE e.activity = 'Remove Payment Block')   AS rpb,
                   count(*) FILTER (WHERE e.activity = 'Record Invoice Receipt') AS ir
            FROM events e JOIN cases c USING (case_id) WHERE e.is_canonical
              AND e.activity IN ('Remove Payment Block', 'Record Invoice Receipt') GROUP BY 1, 2),
        recent AS (
            SELECT l.case_id, sum(v.rpb) AS vendor_rpb_30d, sum(v.ir) AS vendor_ir_30d
            FROM lines l JOIN vday v ON v.vendor = l.vendor
                 AND v.day >= CAST(l.{cut} AS DATE) - 30 AND v.day < CAST(l.{cut} AS DATE)
            GROUP BY 1),
        po AS (SELECT po, count(*) AS po_lines FROM cases GROUP BY 1),
        po_prev AS (  -- other lines of the same PO whose block was removed before this decision point
            SELECT l.case_id, count(DISTINCT e.case_id) AS po_blocked_before
            FROM lines l JOIN cases c2 ON c2.po = l.po AND c2.case_id <> l.case_id
            JOIN events e ON e.case_id = c2.case_id AND e.activity = 'Remove Payment Block' AND e.ts < l.{cut}
            GROUP BY 1)
        SELECT l.case_id, l.ir_ts, l.label::INT AS label, l.value_eur, l.vendor,
               {", ".join(f"coalesce(l.{c}, 'NA') AS {c}" for c in CATEGORICAL)},
               l.gr_based_inv_verif::INT AS gr_based_inv_verif,
               ln(1 + greatest(l.value_eur, 0)) AS log_value,
               date_diff('hour', l.po_ts, l.{cut}) / 24.0 AS days_po_to_cut,
               {"ev.no_gr_yet::INT" if checkpoint == "invoice" else "NULL::INT"} AS invoice_before_gr,
               {", ".join(f"ev.{c}" for c in PRIOR.values())},
               po.po_lines, coalesce(pp.po_blocked_before, 0) AS po_blocked_before,
               ev.value_now / nullif(l.value_eur, 0) AS value_ratio,
               {inv},
               date_diff('hour', ev.last_gr, l.{cut}) / 24.0 AS days_since_gr,
               coalesce(r.vendor_rpb_30d, 0) AS vendor_rpb_30d, coalesce(r.vendor_ir_30d, 0) AS vendor_ir_30d,
               coalesce(r.vendor_rpb_30d, 0) / (coalesce(r.vendor_ir_30d, 0) + 5.0) AS vendor_recent_block_ratio,
               vh.vendor_lines,
               (vh.vendor_blocked + 20 * {global_rate}) / (vh.vendor_lines + 20) AS vendor_block_rate
        FROM lines l JOIN ev USING (case_id) JOIN po ON po.po = l.po
        LEFT JOIN po_prev pp USING (case_id) LEFT JOIN recent r USING (case_id)
        JOIN vendor_hist vh ON vh.vendor = l.vendor AND vh.at_month = l.cut_month
        WINDOW inv AS (PARTITION BY l.vendor, l.ir_ts)
        ORDER BY l.ir_ts, l.case_id
    """)
    cols = [d[0] for d in rows.description]
    data = rows.fetchall()
    return {c: np.array([r[i] for r in data], dtype=object) for i, c in enumerate(cols)}


FEATURES_NUM = ["gr_based_inv_verif", "log_value", "days_po_to_cut", "invoice_before_gr", *PRIOR.values(),
                "po_lines", "po_blocked_before", "vendor_lines", "vendor_block_rate", "value_ratio", "days_since_gr",
                "vendor_rpb_30d", "vendor_ir_30d", "vendor_recent_block_ratio", "inv_lines", "inv_any_no_gr",
                "inv_share_no_gr", "inv_log_value", "inv_any_price_change", "inv_any_qty_change", "ir_dow", "ir_day"]


def matrix(frame: dict, codes: dict[str, dict] | None = None) -> tuple[np.ndarray, list[str], dict]:
    """Numeric feature matrix; categoricals coded on the training rows (unseen values -> 0)."""
    if codes is None:
        codes = {c: {v: i + 1 for i, v in enumerate(sorted(set(frame[c])))} for c in CATEGORICAL}
    cat = np.column_stack([[codes[c].get(v, 0) for v in frame[c]] for c in CATEGORICAL])
    num = np.column_stack([np.array([np.nan if v is None else float(v) for v in frame[c]]) for c in FEATURES_NUM])
    return np.hstack([cat, num]).astype(float), CATEGORICAL + FEATURES_NUM, codes


def take(frame: dict, mask: np.ndarray) -> dict:
    return {k: v[mask] for k, v in frame.items()}


def at_precision(y: np.ndarray, p: np.ndarray, target: float = 0.8) -> dict:
    """Best recall with precision >= target, and the threshold that gives it."""
    order = np.argsort(-p)
    tp = np.cumsum(y[order])
    k = np.arange(1, len(y) + 1)
    prec, rec = tp / k, tp / max(1, y.sum())
    ok = np.where(prec >= target)[0]
    if not len(ok):
        return {"recall": 0.0, "threshold": None, "flagged_share": 0.0}
    i = ok[np.argmax(rec[ok])]
    return {"recall": round(float(rec[i]), 3), "threshold": round(float(p[order][i]), 3),
            "flagged_share": round(float((i + 1) / len(y)), 3)}


def scores(y: np.ndarray, p: np.ndarray) -> dict:
    return {"roc_auc": round(float(roc_auc_score(y, p)), 3), "avg_precision": round(float(average_precision_score(y, p)), 3),
            "brier": round(float(brier_score_loss(y, np.clip(p, 0, 1))), 4), "at_precision_0.8": at_precision(y, p),
            "at_precision_0.7": at_precision(y, p, 0.7), "at_precision_0.6": at_precision(y, p, 0.6)}


def run(checkpoint: str, final: bool = False, target: str = "block", db: Path = DEFAULT_DB) -> dict:
    t0 = time.monotonic()
    con = duckdb.connect(str(db), read_only=True)
    frame = build_frame(con, checkpoint, target=target)
    when = np.array([str(t)[:10] for t in frame["ir_ts"]])
    split = np.where(when < TRAIN_END, "train", np.where(when < CALIB_END, "valid",
                     np.where(when < VALID_END, "dev", "test")))
    y = frame["label"].astype(int)
    print(f"[{checkpoint}] {len(y):,} invoiced lines: train {sum(split == 'train'):,}, calibration "
          f"{sum(split == 'valid'):,}, dev {sum(split == 'dev'):,}, test {sum(split == 'test'):,}; base rate "
          f"{y.mean():.3f} ({time.monotonic() - t0:.0f}s)", flush=True)
    tr, va = split == "train", split == "valid"
    te = split == ("test" if final else "dev")
    X_tr, names, codes = matrix(take(frame, tr))
    X_va, _, _ = matrix(take(frame, va), codes)
    X_te, _, _ = matrix(take(frame, te), codes)
    model = lgb.train(
        {"objective": "binary", "learning_rate": 0.03, "num_leaves": 15, "min_data_in_leaf": 1000, "lambda_l2": 20,
         "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1, "verbose": -1, "seed": 7},
        lgb.Dataset(X_tr, y[tr], feature_name=names, categorical_feature=CATEGORICAL),
        num_boost_round=2000, valid_sets=[lgb.Dataset(X_va, y[va], reference=None)],
        callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(200)])
    raw_va, raw_te = model.predict(X_va), model.predict(X_te)
    iso = IsotonicRegression(out_of_bounds="clip").fit(raw_va, y[va])  # calibration on validation only
    p_te = iso.predict(raw_te)

    rule = np.array([1.0 if v == 1 else 0.0 for v in frame["invoice_before_gr"][te]]) if checkpoint == "invoice" \
        else None
    # the same rule at invoice level (any line on the invoice without a goods receipt), the fairer baseline once the
    # model sees the invoice's other lines
    rule_inv = np.array([1.0 if v == 1 else 0.0 for v in frame["inv_any_no_gr"][te]]) if checkpoint == "invoice" \
        else None
    vendor_only = frame["vendor_block_rate"][te].astype(float)
    report = {
        "checkpoint": checkpoint, "target": target, "scored_on": "test" if final else "dev (Aug 2018)", "horizon_days": HORIZON_DAYS,
        "trees": model.best_iteration,
        "rows": {"train": int(tr.sum()), "calibration": int(va.sum()), "scored": int(te.sum())},
        "base_rate_test": round(float(y[te].mean()), 3),
        "model": scores(y[te], p_te),
        "baseline_vendor_rate": scores(y[te], vendor_only),
        "baseline_rule_invoice_before_gr": scores(y[te], rule) if rule is not None else None,
        "baseline_rule_any_line_before_gr": scores(y[te], rule_inv) if rule_inv is not None else None,
        "seconds": round(time.monotonic() - t0),
    }
    gain = model.feature_importance("gain")
    report["top_features"] = [n for _, n in sorted(zip(-gain, names))][:8]
    MODELS.mkdir(parents=True, exist_ok=True)
    tag = f"{target}-{checkpoint}" if target != "block" else checkpoint
    model.save_model(str(MODELS / f"block-{tag}.txt"), num_iteration=model.best_iteration)
    (MODELS / f"block-{tag}.json").write_text(json.dumps({
        "codes": codes, "features": names, "iso_x": iso.X_thresholds_.tolist(), "iso_y": iso.y_thresholds_.tolist(),
        "threshold_at_precision_0.8": at_precision(y[va], iso.predict(raw_va))["threshold"]}))
    RUNS.mkdir(exist_ok=True)
    out = RUNS / f"predict-{target}-{checkpoint}-{'test' if final else 'dev'}-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps(report, indent=1))
    m, v, r = report["model"], report["baseline_vendor_rate"], report["baseline_rule_invoice_before_gr"]
    ri = report["baseline_rule_any_line_before_gr"]
    print(f"[{checkpoint}/{target}] {'TEST' if final else 'dev'}: model AUC {m['roc_auc']} AP {m['avg_precision']} brier {m['brier']} | "
          f"recall at 80% precision {m['at_precision_0.8']['recall']} (flags {m['at_precision_0.8']['flagged_share']:.1%}"
          f" of invoices), at 60% {m['at_precision_0.6']['recall']} | vendor-rate AUC {v['roc_auc']} AP {v['avg_precision']}"
          + (f" | rule AP {r['avg_precision']} recall@0.8 {r['at_precision_0.8']['recall']} @0.6 "
             f"{r['at_precision_0.6']['recall']}" if r else "")
          + (f" | invoice-rule AP {ri['avg_precision']} @0.8 {ri['at_precision_0.8']['recall']} @0.6 "
             f"{ri['at_precision_0.6']['recall']}" if ri else "")
          + f" -> {out.name}", flush=True)
    return report


def reason(name: str, value) -> str:
    """One feature and its value, as a person would say it."""
    missing = value is None or (isinstance(value, float) and np.isnan(value))
    if name == "invoice_before_gr":
        return "invoice arrived before any goods receipt" if value == 1 else "goods were received before the invoice"
    if name == "days_since_gr":
        return "no goods received yet" if missing else f"goods arrived {float(value):.0f} days before the invoice"
    if name == "n_gr":
        return f"{int(value)} goods receipt(s) recorded so far"
    if name == "vendor_block_rate":
        return f"{REASONS[name]} ({float(value):.0%})"
    if name == "vendor_recent_block_ratio":  # removals / invoices in 30 days: can exceed 1, so not a percentage
        return f"this vendor had {float(value):.1f} block removals per invoice in the last 30 days"
    if name == "vendor_rpb_30d":
        return f"{int(value)} of this vendor's invoices were unblocked in the last 30 days"
    if name == "days_po_to_cut":
        return f"invoice came {float(value):.0f} days after the order"
    if name == "value_ratio" and not missing:
        return f"invoiced amount is {float(value):.0%} of the order"
    if name == "po_lines":
        return f"order has {int(value)} lines"
    if name == "inv_any_no_gr":
        return ("a line on this invoice has no goods receipt yet" if value == 1
                else "every line on this invoice has its goods receipt")
    if name == "inv_share_no_gr" and not missing:
        return f"{float(value):.0%} of this invoice's lines have no goods receipt yet"
    if name == "inv_lines":
        return f"invoice has {int(value)} line(s)"
    if name == "inv_log_value":
        return f"invoice total EUR {np.expm1(float(value)):,.0f}"
    if name in ("inv_any_price_change", "inv_any_qty_change"):
        return REASONS[name] if value == 1 else REASONS[name].replace("had", "had no")
    if name == "ir_user":
        return f"recorded by {value}"
    if name == "ir_dow":
        return f"recorded on a {['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'][int(value)]}"
    if name == "ir_day":
        return f"recorded on day {int(value)} of the month"
    if name == "log_value":
        return f"line value EUR {np.expm1(float(value)):,.0f}"
    counts = {"n_vendor_invoice": "vendor invoice(s) on this line", "n_change_price": "price change(s) on the order",
              "n_change_qty": "quantity change(s) on the order", "n_order_conf": "order confirmation(s)",
              "n_cancel_gr": "cancelled goods receipt(s)", "n_change_approval": "approval change(s)",
              "n_service_entry": "service entry sheet(s)", "po_blocked_before": "other line(s) of this order blocked",
              "vendor_ir_30d": "invoice(s) from this vendor in the last 30 days"}
    if name in counts:
        return f"{int(value)} {counts[name]}"
    if name == "has_requisition":
        return "came from a purchase requisition" if value else "no purchase requisition"
    if name in CATEGORICAL:
        return f"{REASONS[name]}: {'not recorded' if value == 'NA' else value}"
    return REASONS.get(name, name) if missing else f"{REASONS.get(name, name)}: {value}"


def worklist(db: Path = DEFAULT_DB) -> dict:
    """Score every invoice still open at the end of the data (recorded in the last 60 days, no block removed yet, not
    paid) with the invoice-time model; keep the three features that pushed each score up most (SHAP values from the
    trees) as the reasons a person reads. Written to the warehouse as m_block_risk."""
    model = lgb.Booster(model_file=str(MODELS / "block-invoice.txt"))
    meta = json.loads((MODELS / "block-invoice.json").read_text())
    con = duckdb.connect(str(db))
    data_end = con.execute("SELECT data_end FROM m_data_end").fetchone()[0]
    frame = build_frame(con, "invoice", until="2100-01-01")
    open_ids = {r[0] for r in con.execute("""
        SELECT case_id FROM events e GROUP BY case_id
        HAVING min(ts) FILTER (WHERE activity = 'Record Invoice Receipt') >= ? - INTERVAL 60 DAY
           AND count(*) FILTER (WHERE activity IN ('Remove Payment Block', 'Clear Invoice')) = 0
    """, [data_end]).fetchall()}
    keep = np.array([c in open_ids for c in frame["case_id"]])
    f = take(frame, keep)
    X, names, _ = matrix(f, meta["codes"])
    raw = model.predict(X)
    p = np.interp(raw, meta["iso_x"], meta["iso_y"])
    contrib = model.predict(X, pred_contrib=True)[:, :-1]  # last column is the bias
    thr = meta["threshold_at_precision_0.8"] or 0.5
    rows = []
    for i in range(len(p)):
        order = [names[j] for j in np.argsort(-contrib[i]) if contrib[i][j] > 0]
        if f["invoice_before_gr"][i] == 1 or f["inv_any_no_gr"][i] == 1:  # "no goods yet" said once, not three ways
            keep = next((n for n in order if n in ("inv_share_no_gr", "inv_any_no_gr", "invoice_before_gr")), None)
            order = [n for n in order if n not in ("n_gr", "days_since_gr", "inv_share_no_gr", "inv_any_no_gr",
                                                   "invoice_before_gr") or n == keep]
        top = order[:3]
        rows.append((f["case_id"][i], f["vendor"][i], float(f["value_eur"][i]), str(f["ir_ts"][i])[:10],
                     round(float(p[i]), 3), bool(p[i] >= thr), [reason(n, f[n][i]) for n in top]))
    con.execute("""CREATE OR REPLACE TABLE m_block_risk (case_id VARCHAR, vendor VARCHAR, value_eur DOUBLE,
                   invoice_recorded DATE, p_block DOUBLE, flagged BOOLEAN, reasons VARCHAR[])""")
    con.executemany("INSERT INTO m_block_risk VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    summary = con.execute("SELECT count(*), count(*) FILTER (WHERE flagged), round(sum(value_eur) FILTER (WHERE flagged))"
                          " FROM m_block_risk").fetchone()
    con.close()
    print(f"worklist: {summary[0]:,} open invoices scored, {summary[1]:,} flagged (threshold {thr}), "
          f"EUR {summary[2]:,.0f} flagged")
    return {"open": summary[0], "flagged": summary[1], "eur_flagged": summary[2], "threshold": thr}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", choices=["po", "invoice", "both"], default="both")
    ap.add_argument("--final", action="store_true", help="score the test months (once, at the end)")
    ap.add_argument("--target", choices=["block", "human"], default="block")
    ap.add_argument("--worklist", action="store_true", help="score the invoices open at the end of the data")
    a = ap.parse_args()
    if a.worklist:
        worklist()
        return
    for cp in (["po", "invoice"] if a.checkpoint == "both" else [a.checkpoint]):
        run(cp, a.final, a.target)


if __name__ == "__main__":
    main()
