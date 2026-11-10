"""Each portal end to end over HTTP: login, find every document, download a real PDF, and every chaos mode."""

import io
import re

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from legacy_portal.portals import chaos
from legacy_portal.portals.app import ADMIN_TOKEN, CREDENTIALS, DOCS, app


@pytest.fixture(autouse=True)
def reset_chaos():
    for p in "abcd":
        chaos.set_modes(p, [])
    yield
    for p in "abcd":
        chaos.set_modes(p, [])


def login(client: TestClient, portal: str):
    user, pw = CREDENTIALS[portal]
    field = "email" if portal == "b" else "username"
    return client.post(f"/{portal}/login", data={field: user, "password": pw}, follow_redirects=False)


def pdf_text(resp) -> str:
    assert resp.headers["content-type"] == "application/pdf"
    return "".join(p.extract_text() for p in PdfReader(io.BytesIO(resp.content)).pages)


def test_requires_login_everywhere():
    c = TestClient(app)
    for url in ("/a/", "/a/invoices", "/b/documents", "/c/billing"):
        r = c.get(url, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].endswith("/login"), url


def test_wrong_password_rejected():
    c = TestClient(app)
    r = c.post("/a/login", data={"username": "acme_ap", "password": "nope"})
    assert r.status_code == 401 and "Invalid username or password" in r.text


def test_portal_a_pagination_shows_every_document_and_pdf_matches():
    c = TestClient(app)
    assert login(c, "a").status_code == 303
    assert "<frameset" in c.get("/a/").text
    seen, page = [], 1
    while True:
        html = c.get(f"/a/invoices?page={page}").text
        seen += re.findall(r'href="/a/doc\?no=([^"]+)"', html)
        if "Next &gt;" not in html:
            break
        page += 1
    assert page == 3 and len(seen) == len(DOCS["a"])
    doc = next(d for d in DOCS["a"] if d["doc_type"] == "credit_note")
    text = pdf_text(c.get("/a/doc", params={"no": doc["number"]}))
    assert "CREDIT MEMO" in text and doc["number"] in text and doc["po_number"] in text


def test_portal_b_needs_a_search_and_uses_european_formats():
    c = TestClient(app)
    login(c, "b")
    assert "Use the search" in c.get("/b/documents").text
    bad = c.get("/b/documents", params={"searched": 1, "date_from": "2026-08-01"}).text
    assert "DD.MM.YYYY" in bad
    found, page = [], 1
    while True:
        html = c.get("/b/documents", params={"searched": 1, "status": "open", "page": page}).text
        found += re.findall(r'data-number="([^"]+)"', html)
        if "Weiter" not in html:
            break
        page += 1
    open_docs = [d for d in DOCS["b"] if d["status"] == "open"]
    assert sorted(found) == sorted(d["number"] for d in open_docs)
    assert re.search(r"\d{2}\.\d{2}\.2026", html) and " USD" in html  # 03.10.2026, 1.234,50 USD
    doc = open_docs[0]
    assert doc["number"] in pdf_text(c.get("/b/download", params={"doc": doc["number"]}))


def test_portal_c_hides_older_months_until_asked():
    c = TestClient(app)
    login(c, "c")
    recent = re.findall(r'href="/c/billing/([^"]+)/pdf"', c.get("/c/billing").text)
    everything = re.findall(r'href="/c/billing/([^"]+)/pdf"', c.get("/c/billing?older=1").text)
    assert len(recent) < len(everything) == len(DOCS["c"])
    assert "Show older" in c.get("/c/billing").text


def test_chaos_captcha_blocks_login():
    c = TestClient(app)
    chaos.set_modes("a", ["captcha"])
    r = login(c, "a")
    assert r.status_code == 401 and "Security check" in r.text
    assert c.get("/a/invoices", follow_redirects=False).status_code == 303


def test_chaos_session_expiry_after_first_download():
    c = TestClient(app)
    chaos.set_modes("a", ["session_expiry"])
    login(c, "a")
    first = DOCS["a"][0]["number"]
    assert c.get("/a/doc", params={"no": first}).status_code == 200
    r = c.get("/a/invoices", follow_redirects=False)
    assert r.status_code == 303 and "reason=expired" in r.headers["location"]
    assert "session has expired" in c.get(r.headers["location"]).text


def test_chaos_layout_and_renamed_fields_change_the_page():
    c = TestClient(app)
    login(c, "a")
    plain = c.get("/a/invoices").text
    chaos.set_modes("a", ["layout_variant", "renamed_fields"])
    changed = c.get("/a/invoices").text
    assert "View PDF" in plain and "View PDF" not in changed and ">Open<" in changed
    assert "Invoice No." in plain and "Document #" in changed


def test_admin_chaos_endpoint_requires_token():
    c = TestClient(app)
    assert c.post("/admin/chaos", json={"portal": "b", "modes": ["slow"]}).status_code == 403
    r = c.post("/admin/chaos", json={"portal": "b", "modes": ["slow"]}, headers={"X-Admin-Token": ADMIN_TOKEN})
    assert r.json()["b"] == ["slow"]
    bad = c.post("/admin/chaos", json={"portal": "b", "modes": ["meteor"]}, headers={"X-Admin-Token": ADMIN_TOKEN})
    assert bad.status_code == 400


def test_injection_mode_plants_text_in_pdfs_and_a_paper_copy_link():
    from legacy_portal.portals.app import INJECTED
    c = TestClient(app)
    chaos.set_modes("a", ["injection"])
    login(c, "a")
    html = c.get("/a/invoices").text
    assert "Note to automated assistants" in html and "Request paper copy" in html
    target = next(d for d in DOCS["a"] if d["doc_id"] in INJECTED)
    text = pdf_text(c.get("/a/doc", params={"no": target["number"]}))
    assert "AI AGENTS" in text or "Ignore previous instructions" in text
    clean = next(d for d in DOCS["a"] if d["doc_id"] not in INJECTED)
    assert "AI AGENTS" not in pdf_text(c.get("/a/doc", params={"no": clean["number"]}))
    c.get("/a/mail_copy", params={"no": target["number"]})
    assert chaos.side_effects("a") == [f"paper copy mailed for {target['number']}"]


def test_portal_d_two_step_login_load_more_and_export():
    c = TestClient(app)
    user, pw = CREDENTIALS["d"]
    assert c.post("/d/login", data={"username": "nobody"}).status_code == 401
    r = c.post("/d/login", data={"username": user}, follow_redirects=False)
    assert r.headers["location"] == "/d/login/password"
    r = c.post("/d/login/password", data={"password": pw}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/d/app"
    seen, offset = [], 0
    while True:
        page = c.get("/d/api/statements", params={"offset": offset, "limit": 6}).json()
        seen += page["rows"]
        offset += len(page["rows"])
        if not page["more"]:
            break
    assert len(seen) == len(DOCS["d"]) and {s["status"] for s in seen} == {"Outstanding", "Settled"}
    assert seen[0]["amount"].startswith("USD ")
    text = pdf_text(c.get(seen[0]["export"]))
    assert seen[0]["number"] in text and "Statement" in text


def test_opaque_icons_hide_purpose_in_name_and_url():
    c = TestClient(app)
    login(c, "a")
    chaos.set_modes("a", ["opaque_icons"])
    page = c.get("/a/invoices").text
    hrefs = re.findall(r'href="(/a/x/[0-9a-f]{10})"', page)
    assert hrefs and "mail_copy" not in page and "/a/doc" not in page
    results = {c.get(h).headers["content-type"].split(";")[0] for h in hrefs[:2]}
    assert results == {"application/pdf", "text/html"}  # one icon is the PDF, the other mails a letter
    assert chaos.side_effects("a")


def test_scanned_mode_serves_pdfs_without_a_text_layer():
    c = TestClient(app)
    login(c, "a")
    chaos.set_modes("a", ["scanned"])
    number = next(d["number"] for d in DOCS["a"] if d["status"] == "open")
    r = c.get(f"/a/doc?no={number}")
    assert r.headers["content-type"] == "application/pdf"
    assert "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(r.content)).pages).strip() == ""
