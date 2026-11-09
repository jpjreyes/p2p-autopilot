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


def test_new_tab_is_closed_and_reported(tools):
    tools.page.set_content('<a href="about:blank" target="_blank">Open</a>')
    res = tools.run({"action": "click", "role": "link", "name": "Open"})
    assert res.ok and "new tab" in res.message and len(tools.page.context.pages) == 1


def test_navigation_outside_the_portal_is_blocked(tools):
    res = tools.run({"action": "goto", "value": "https://example.com/"})
    assert not res.ok and "outside the allowed portal" in res.message
