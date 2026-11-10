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
