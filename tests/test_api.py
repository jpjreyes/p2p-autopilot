"""Console API against a real Postgres: decisions, guardrails, and concurrent requests (the bug that broke approve)."""

import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs DATABASE_URL")


@pytest.fixture(scope="module")
def client():
    from legacy_portal.api import POOL, app
    from legacy_portal.pipeline import ReviewItem
    from legacy_portal.runstore import RunStore

    with TestClient(app) as c:  # runs the lifespan: pool open + schema once
        with POOL.connection() as conn:
            rs = RunStore(conn)
            conn.execute("DELETE FROM runs WHERE run_id='test-run'")
            rs.start("test-run", "a")
            rs.save_review("test-run", [
                ReviewItem("INV-T1", "x.pdf", "proposed", "match", "10.00", ["ok"], "agree", 1,
                           {"po_number": "PO-NOPE", "total": "10.00"}),
                ReviewItem("INV-T2", "y.pdf", "needs_human", "unknown_po", None, ["no PO"], "agree", 1)])
        yield c
        with POOL.connection() as conn:
            conn.execute("DELETE FROM runs WHERE run_id='test-run'")


def item(client, number):
    return next(i for i in client.get("/api/review").json() if i["number"] == number)


def test_concurrent_requests_do_not_fail(client):
    with ThreadPoolExecutor(8) as ex:
        codes = list(ex.map(lambda _: client.get("/api/review").status_code, range(24)))
    assert set(codes) == {200}


def test_approve_once_then_conflict(client):
    i = item(client, "INV-T1")
    r = client.post(f"/api/review/{i['item_id']}", json={"decision": "approve"})
    assert r.status_code == 200 and r.json()["status"] == "approved_for_payment"
    assert client.post(f"/api/review/{i['item_id']}", json={"decision": "reject"}).status_code == 409


def test_bad_decision_rejected(client):
    i = item(client, "INV-T2")
    assert client.post(f"/api/review/{i['item_id']}", json={"decision": "pay"}).status_code == 400


def test_held_out_portal_and_unknown_chaos_are_refused(client):
    assert client.post("/api/runs", json={"portal": "d"}).status_code == 400
    assert client.post("/api/runs", json={"portal": "a", "chaos": "meteor"}).status_code == 400


def test_item_detail_and_page_guard(client):
    i = item(client, "INV-T1")
    detail = client.get(f"/api/review/{i['item_id']}").json()
    assert detail["item"]["extracted"]["total"] == "10.00" and detail["order"] is None  # unknown PO: no order
    assert client.get(f"/api/review/{i['item_id']}/page.png").status_code == 404  # file outside runs/: refused
    assert client.get("/api/review/999999").status_code == 404
