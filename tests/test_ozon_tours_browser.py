import asyncio

import httpx
import pytest

from marketplaces_mcp.core.ozon_tours_access import OzonToursAccess, classify_page
from marketplaces_mcp.core.ozon_tours_browser import OzonToursBrowser, URL, USER_ID


def browser_fixture(*, existing=True, captcha=True, multiple=False, nav_status=200):
    calls = []
    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path == "/tabs" and request.method == "GET":
            return httpx.Response(200, json={"tabs": [dict(tabId="kept", url=URL, listItemId="readonly")] *
                                           (2 if multiple else int(existing))})
        if request.url.path == "/tabs":
            import json
            assert "url" not in json.loads(request.content)
            return httpx.Response(200, json={"tabId": "kept"})
        if request.url.path.endswith("/navigate"):
            return httpx.Response(nav_status, json={"error": "navigation timed out"})
        if request.url.path.endswith("/evaluate"):
            return httpx.Response(200, json={"result": {"title": "Туры", "captcha_frame": captcha,
                                                       "text": "Город вылета Ночей Найти туры"}})
        raise AssertionError(f"Unexpected {request.method} {request.url.path}")
    return OzonToursBrowser("http://localhost", transport=httpx.MockTransport(handler)), calls


def test_existing_captcha_survives_and_does_not_navigate_or_disappear(tmp_path):
    browser, calls = browser_fixture()
    a = OzonToursAccess(browser, tmp_path / "state.json")
    state = asyncio.run(a.status(probe=True))
    assert state["status"] == "OZON_TOURS_CAPTCHA_REQUIRED"
    assert state["browser_tab_id"] == "kept" and state["tab_preserved"]
    assert state["requires_user_action"] and state["search_supported"]
    assert calls == [("GET", "/tabs"), ("POST", "/tabs/kept/evaluate")]
    assert "captcha.html" not in str(state)


def test_navigation_500_still_reads_same_page_instead_of_losing_tab():
    browser, calls = browser_fixture(existing=False, nav_status=500)
    state = asyncio.run(browser(URL))
    assert state["status"] == "OZON_TOURS_CAPTCHA_REQUIRED"
    assert calls == [("GET", "/tabs"), ("POST", "/tabs"),
                     ("POST", "/tabs/kept/navigate"), ("POST", "/tabs/kept/evaluate")]


def test_manual_completion_can_be_checked_during_cooldown_without_reload(tmp_path):
    browser, calls = browser_fixture(captcha=False)
    access = OzonToursAccess(browser, tmp_path / "state.json")
    access.write({"status": "OZON_TOURS_CAPTCHA_REQUIRED", "retry_after": 9999999999})
    state = asyncio.run(access.status(inspect_tab=True))
    assert state["status"] == "OZON_TOURS_PAGE_AVAILABLE"
    assert state["retry_after"] == 9999999999
    assert not state["requires_user_action"] and state["search_supported"]
    assert calls == [("GET", "/tabs"), ("POST", "/tabs/kept/evaluate")]


def test_inspection_never_creates_page_or_navigates_when_tab_is_missing():
    browser, calls = browser_fixture(existing=False)
    assert asyncio.run(browser.inspect())["status"] == "OZON_TOURS_NO_OPEN_TAB"
    assert calls == [("GET", "/tabs")]


def test_multiple_matching_tabs_are_not_silently_selected():
    browser, calls = browser_fixture(multiple=True)
    assert asyncio.run(browser(URL))["status"] == "OZON_TOURS_MULTIPLE_TABS"
    assert calls == [("GET", "/tabs")]


@pytest.mark.parametrize("heading", ["Antibot Captcha", "Сопоставьте пазл, двигая ползунок",
                                   "Slide the slider to fit the puzzle"])
def test_captcha_heading_is_distinct_from_network_error(heading):
    assert classify_page(f"<h1>{heading}</h1>") == "OZON_TOURS_CAPTCHA_REQUIRED"


def test_browser_only_opens_fixed_public_tours_page():
    browser, calls = browser_fixture()
    with pytest.raises(ValueError):
        asyncio.run(browser("https://www.ozon.ru/checkout"))
    assert not calls
