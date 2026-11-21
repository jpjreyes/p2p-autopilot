import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals" / "finetune"))


def test_cash_rounding_matches_malaysian_rule():
    from score import cash_round
    assert cash_round(Decimal("7.42")) == Decimal("7.40")
    assert cash_round(Decimal("7.43")) == Decimal("7.45")
    assert cash_round(Decimal("7.48")) == Decimal("7.50")
    assert cash_round(Decimal("10.00")) == Decimal("10.00")


def test_judge_strict_vs_adjusted_total():
    from score import judge
    gt = {"company": "ABC SDN BHD", "address": "1 JALAN X", "date": "21/02/2018", "total": "7.42"}
    paid = judge({"company": "ABC SDN BHD", "address": "1 JALAN X", "date": "2018-02-21", "total": "7.40"}, gt)
    assert paid["total_strict"] is False and paid["total_adjusted"] is True and paid["date"] is True
    unparsed = judge(None, gt)
    assert unparsed["parsed"] is False and unparsed["total_and_date"] is False


def test_registry_gate_rule():
    pytest.importorskip("mlflow")
    from p2p_autopilot.process.registry import gate
    champ = {"model": {"avg_precision": 0.545, "brier": 0.1652}}
    assert gate(champ, {"model": {"avg_precision": 0.515, "brier": 0.1701}})[0] is False
    assert gate(champ, {"model": {"avg_precision": 0.551, "brier": 0.1660}})[0] is True
    assert gate(champ, {"model": {"avg_precision": 0.560, "brier": 0.1700}})[0] is False  # better AP, worse calibration
