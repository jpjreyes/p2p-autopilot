import json

from legacy_portal import chaos_suite


def test_save_is_atomic_and_leaves_no_temp_file(tmp_path):
    out = tmp_path / "r.json"
    chaos_suite.save(out, [{"portal": "a", "mode": "none", "rep": 0}])
    chaos_suite.save(out, [{"portal": "a", "mode": "none", "rep": 0}, {"portal": "a", "mode": "slow", "rep": 0}])
    assert len(json.loads(out.read_text())) == 2
    assert [p.name for p in tmp_path.iterdir()] == ["r.json"]


def test_portal_down_is_detected():
    assert chaos_suite.portal_up("http://127.0.0.1:9") is False
