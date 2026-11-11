"""Payment-block model (D18): the operating-point math, the reasons, and that features never see the future."""

import numpy as np
import pytest

from legacy_portal.process.predict import at_precision, reason
from legacy_portal.process.warehouse import DEFAULT_DB


def test_at_precision_picks_the_best_recall_that_keeps_precision():
    y = np.array([1, 1, 0, 1, 0, 0, 0, 1])
    p = np.array([0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2])
    # top 2 are both right (precision 1.0, recall 0.5); top 4 = 3/4 right (0.75 < 0.8)
    assert at_precision(y, p, 0.8) == {"recall": 0.5, "threshold": 0.8, "flagged_share": 0.25}
    assert at_precision(y, p, 0.75)["recall"] == 0.75
    assert at_precision(np.array([0, 0]), np.array([0.9, 0.1]))["recall"] == 0.0


def test_reasons_read_like_a_person_would_say_them():
    assert reason("invoice_before_gr", 1) == "invoice arrived before any goods receipt"
    assert reason("days_since_gr", float("nan")) == "no goods received yet"
    assert reason("vendor_block_rate", 0.41) == "this vendor's invoices were often blocked before (41%)"
    assert reason("log_value", float(np.log1p(78490))) == "line value EUR 78,490"
    assert reason("sub_spend_area", "NA") == "sub spend area: not recorded"


@pytest.mark.skipif(not DEFAULT_DB.exists(), reason="warehouse not built")
def test_invoice_features_only_use_events_before_the_invoice():
    import duckdb

    from legacy_portal.process.predict import build_frame
    con = duckdb.connect(str(DEFAULT_DB), read_only=True)
    f = build_frame(con, "invoice")
    rng = np.random.default_rng(1)
    for i in rng.choice(len(f["case_id"]), size=50, replace=False):
        case, ir = f["case_id"][i], f["ir_ts"][i]
        n_gr = con.execute("SELECT count(*) FROM events WHERE case_id = ? AND is_canonical AND "
                           "activity = 'Record Goods Receipt' AND ts < ?", [case, ir]).fetchone()[0]
        assert f["n_gr"][i] == n_gr
        assert f["invoice_before_gr"][i] == int(n_gr == 0)
