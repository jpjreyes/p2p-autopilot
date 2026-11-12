"""BrowserTools in a real headless Chromium (skipped if Playwright's browser isn't installed)."""

import pytest
from playwright.sync_api import Error as PWError
from playwright.sync_api import sync_playwright

from legacy_portal.browser import BrowserTools


@pytest.fixture
def tools(tmp_path):
    try:
        p = sync_playwright().start()
        browser = p.chromium.launch()
    except PWError as e:
        pytest.skip(f"chromium not installed: {e}")
    page = browser.new_page()
    yield BrowserTools(page, "http://127.0.0.1", {"username": "u", "password": "secret"}, tmp_path)
    browser.close()
    p.stop()


def test_ambiguous_target_is_an_error_and_nth_picks_one(tools):
    tools.page.set_content("<input aria-label=''><input aria-label=''>")
    assert not tools.run({"action": "fill", "role": "textbox", "name": "", "value": "x"}).ok
    assert tools.run({"action": "fill", "role": "textbox", "name": "", "value": "{{password}}", "nth": 1}).ok
    assert tools.page.locator("input").nth(1).input_value() == "secret"  # placeholder replaced in code only


def test_fill_without_value_fails_instead_of_typing_nothing(tools):
    """Found by the no-look ablation (D13): the model put {{password}} in "text" and the old tool reported ok."""
    tools.page.set_content("<input aria-label='User'>")
    res = tools.run({"action": "fill", "role": "textbox", "name": "User", "text": "{{username}}"})
    assert not res.ok and "needs" in res.message and "text" in res.message


def test_nameless_link_needs_a_mark_not_a_guess(tools):
    """D13: without vision the agent mailed letters by clicking nameless icons by position or opening their URLs."""
    tools.allowed_origin = "http://127.0.0.1"
    tools.page.route("http://127.0.0.1/**", lambda r: r.fulfill(
        body='<a href="/x/1"><img src="data:,"></a> <a href="/x/2"><img src="data:,"></a>', content_type="text/html"))
    tools.page.goto("http://127.0.0.1/list")
    for action in ({"action": "click", "role": "link", "name": "", "nth": 0},
                   {"action": "download", "role": "link", "name": "", "nth": 1},
                   {"action": "goto", "value": "/x/1"}):
        res = tools.run(action)
        assert not res.ok and "mark" in res.message, action
    tools.look()
    assert len(tools.marks) == 2  # after a look, the seen elements are usable by mark


def test_new_tab_is_closed_and_reported(tools):
    tools.page.set_content('<a href="about:blank" target="_blank">Open</a>')
    res = tools.run({"action": "click", "role": "link", "name": "Open"})
    assert res.ok and "new tab" in res.message and len(tools.page.context.pages) == 1


def test_navigation_outside_the_portal_is_blocked(tools):
    res = tools.run({"action": "goto", "value": "https://example.com/"})
    assert not res.ok and "outside the allowed portal" in res.message


def test_look_marks_unlabeled_icons_and_mark_targets_the_exact_one(tools):
    tools.page.set_content('<a href="#mail" id="m"><img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" '
                           'width="20" height="20"></a> <a href="#pdf" id="p"><img src="data:image/gif;base64,'
                           'R0lGODlhAQABAAAAACw=" width="20" height="20"></a>')
    png, legend = tools.look()
    assert png[:4] == b"\x89PNG" and len(tools.marks) == 2 and "[2] link" in legend
    assert not tools.run({"action": "click", "role": "link", "name": ""}).ok  # ambiguous by name
    assert tools.run({"action": "click", "mark": 2}).ok
    assert tools.page.url.endswith("#pdf")
    assert not tools.run({"action": "click", "mark": 9}).ok  # unknown mark: an error, never a guess


def test_click_by_text_opens_a_collapsed_section_and_marks_include_summary(tools):
    tools.page.set_content("<details><summary>September 2026 (5)</summary><a href='#doc'>PDF</a></details>")
    assert not tools.page.get_by_role("link", name="PDF").is_visible()
    _, legend = tools.look()
    assert "September 2026" in legend  # <summary> has no standard role but is marked
    assert tools.run({"action": "click", "text": "September 2026 (5)"}).ok
    assert tools.page.get_by_role("link", name="PDF").is_visible()


def test_look_covers_the_whole_page_not_just_the_window(tools):
    tools.page.set_viewport_size({"width": 800, "height": 300})
    tools.page.set_content("<div style='height:1500px'>top</div><a href='#end'>Last link</a>")
    png, legend = tools.look()
    import io

    from PIL import Image
    assert "Last link" in legend and Image.open(io.BytesIO(png)).height > 1000


# Export buttons (held-out Portal D, D24): no href; a script opens the file in a new tab or makes a download.
# _fetch_pdf uses the context's request client, which bypasses page routes, so these use a real local server.
@pytest.fixture
def export_site():
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    pdf = b"%PDF-1.4\n%%EOF\n"
    page = """<button onclick="window.open('/export?no=INV-7', '_blank')">Export</button>
<button onclick="window.open('/login?next=export', '_blank')">Export expired</button>
<button onclick="const a=document.createElement('a');
  a.href=window.URL.createObjectURL(new Blob(['%PDF-1.4\\n%%EOF\\n'],{type:'application/pdf'}));
  a.download='INV-8.pdf'; document.body.appendChild(a); a.click();">Export blob</button>
<button onclick="void 0">Export nothing</button>"""

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/export"):
                body, ctype = pdf, "application/pdf"
                extra = {"Content-Disposition": 'attachment; filename="INV-7.pdf"'}
            elif self.path.startswith("/login"):
                body, ctype, extra = b'<form><input type="password"></form>', "text/html", {}
            else:
                body, ctype, extra = page.encode(), "text/html", {}
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            for k, v in extra.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_export_button_that_opens_the_pdf_in_a_new_tab_is_saved(tools, export_site):
    tools.allowed_origin = export_site
    tools.page.goto(f"{export_site}/list")
    res = tools.run({"action": "download", "role": "button", "name": "Export"})
    assert res.ok and res.downloaded.endswith("INV-7.pdf"), res.message
    assert len(tools.page.context.pages) == 1  # the extra tab is closed


def test_scripted_blob_download_is_saved_and_checked_as_pdf(tools, export_site):
    tools.allowed_origin = export_site
    tools.page.goto(f"{export_site}/list")
    res = tools.run({"action": "download", "role": "button", "name": "Export blob"})
    assert res.ok and res.downloaded.endswith("INV-8.pdf"), res.message


def test_export_into_an_expired_session_says_so(tools, export_site):
    tools.allowed_origin = export_site
    tools.page.goto(f"{export_site}/list")
    res = tools.run({"action": "download", "role": "button", "name": "Export expired"})
    assert not res.ok and "session expired" in res.message


def test_button_that_produces_nothing_is_a_clear_failure(tools, export_site):
    tools.allowed_origin = export_site
    tools.page.goto(f"{export_site}/list")
    res = tools.run({"action": "download", "role": "button", "name": "Export nothing"})
    assert not res.ok and "opened no file" in res.message and not tools.downloads
