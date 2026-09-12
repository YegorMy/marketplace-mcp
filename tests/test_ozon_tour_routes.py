"""Route-independent contracts using synthetic IDs, never live catalogue claims."""
import asyncio
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode, urlsplit

import pytest

from marketplaces_mcp.adapters.ozon_tours import (
    OzonToursAdapter, SEARCH, canonical_search_url, parse_leads, parse_rates, search_context,
)
from marketplaces_mcp.core.ozon_tours_access import OzonToursAccess
from marketplaces_mcp.mcp_server import server

FIXTURES = Path(__file__).parent / "fixtures"


def search_url(**changes):
    params = dict(fromCity="100001", toCountry="200001", startDate="2026-12-19",
                  minNight="5", maxNight="7", Dlts="3", Children="0,8")
    params.update(changes)
    return SEARCH + "?" + urlencode({k: v for k, v in params.items() if v is not None})


@pytest.mark.parametrize("origin,destination", [("100001", "200001"), ("100002", "200003"),
                                              ("140212000", "210915000")])
def test_quotes_accept_different_routes_without_a_hardcoded_catalogue(origin, destination):
    url = search_url(fromCity=origin, toCountry=destination)
    leads = parse_leads({"url": url, "html": (FIXTURES / "ozon_tours_search.html").read_text()}, url)
    assert leads and all(lead["total_price"] is None for lead in leads)
    data = {
        "url": "https://www.ozon.ru/travel/tours/hotel?" + urlencode({
            "date": "2026-12-19", "searchRawQuery": urlsplit(url).query}),
        "hotel": "Fixture hotel",
        "detail": (FIXTURES / "ozon_tours_rooms.html").read_text(),
    }
    rates = parse_rates(data, url, "Fixture hotel")
    assert rates and rates[0]["total_price"] == 311787
    assert all(rate["child_ages"] == [0, 8] and rate["flight_selection_pending"] for rate in rates)
    assert all(rate["return_date"] is None for rate in rates)
    with pytest.raises(ValueError, match="different trip"):
        parse_rates(data, search_url(fromCity=origin, toCountry="999999"), "Fixture hotel")


@pytest.mark.parametrize("missing", ["fromCity", "toCountry", "startDate", "minNight", "maxNight", "Dlts"])
def test_incomplete_links_are_rejected(missing):
    with pytest.raises(ValueError, match="Incomplete"):
        search_context(search_url(**{missing: None}))


@pytest.mark.parametrize("change", [
    {"fromCity": "0"}, {"toCountry": "-1"}, {"fromCity": "Москва"},
    {"toCountry": ""}, {"Dlts": "0"}, {"Dlts": "7"}, {"Dlts": "1.5"},
    {"Children": ""}, {"Children": "17"}, {"Children": "0,,8"}, {"Children": "0,1,2,3"},
    {"minNight": "8", "maxNight": "7"}, {"minNight": "1"}, {"maxNight": "22"},
    {"minNight": "5", "maxNight": "10"}, {"startDate": "2026-02-30"},
    {"startDate": "20261219"}, {"mealTypes": ""}, {"mealTypes": "ozon_ai,,ozon_uai"},
    {"mealTypes": "unverified_meal_code"},
    {"rooms": "2"}, {"toCity": "300001"}, {"unknown_trip_filter": "value"},
])
def test_invalid_or_unhandled_trip_filters_are_not_silently_dropped(change):
    with pytest.raises(ValueError):
        search_context(search_url(**change))


@pytest.mark.parametrize("url", [
    search_url() + "&fromCity=100002", search_url() + "&Children=1",
    search_url().replace("https://", "http://"),
    search_url().replace("www.ozon.ru", "www.ozon.ru.evil.test"),
    search_url().replace("www.ozon.ru", "user@www.ozon.ru"),
    search_url().replace("www.ozon.ru", "www.ozon.ru:443"),
    search_url().replace("/tours/search", "/checkout"), search_url() + "#other-trip",
])
def test_ambiguous_or_non_search_links_are_rejected(url):
    with pytest.raises(ValueError):
        search_context(url)


def test_normalization_preserves_the_trip_and_discards_only_known_tracking():
    url = search_url(Children="8,0", mealTypes="ozon_uai,ozon_ai", utm_source="fixture")
    canonical = canonical_search_url(url)
    assert "utm_source" not in canonical
    context = search_context(canonical)
    assert context == search_context(url)
    assert context["Children"] == "0,8"
    assert context["mealTypes"] == "ozon_ai,ozon_uai"
    assert context["fromCity"] == "100001" and context["toCountry"] == "200001"


def test_room_quotes_obey_the_specific_meal_filter_in_the_link():
    url = search_url(mealTypes="ozon_ai")
    data = {
        "url": "https://www.ozon.ru/travel/tours/hotel?" + urlencode({
            "date": "2026-12-19", "searchRawQuery": urlsplit(url).query}),
        "hotel": "Fixture hotel",
        "detail": (FIXTURES / "ozon_tours_rooms.html").read_text(),
    }
    rates = parse_rates(data, url, "Fixture hotel", all_inclusive_only=False)
    assert rates
    assert {rate["meal_plan"] for rate in rates} == {"Всё включено"}


def test_public_url_mode_dispatches_the_complete_request(monkeypatch):
    called = []

    async def search_by_url(**kwargs):
        called.append(kwargs)
        return {"source_url": kwargs["search_url"], "offers": []}

    monkeypatch.setattr(server, "_ozon_package_adapter", SimpleNamespace(search_by_url=search_by_url))
    response = asyncio.run(server.ozon_travel_tours_search(search_url=search_url(), limit=4))
    assert response.warnings == []
    assert called == [{"search_url": canonical_search_url(search_url()), "limit": 4}]
    assert search_context(response.source_url)["toCountry"] == "200001"


@pytest.mark.parametrize("criteria", [{"origin": "LED"}, {"departure_date": "2026-12-19"},
                                     {"adults": 2}, {"rooms": 1}, {"child_ages": []},
                                     {"all_inclusive_only": False}])
def test_link_and_separate_criteria_cannot_silently_disagree(monkeypatch, criteria):
    monkeypatch.setattr(server, "_ozon_package_adapter", object())
    response = asyncio.run(server.ozon_travel_tours_search(search_url=search_url(), **criteria))
    assert response.warnings == ["INVALID_TOUR_REQUEST"]
    assert not response.offers


def test_unknown_names_request_a_link_instead_of_guessing_ids(monkeypatch):
    monkeypatch.setattr(server, "_ozon_package_adapter", object())
    response = asyncio.run(server.ozon_travel_tours_search(
        origin="Example city", destination="Example country", departure_date="2026-12-19"))
    assert response.warnings == ["OZON_TOURS_ROUTE_LOOKUP_REQUIRED"]
    assert "search_url" in response.note
    assert response.source_url == "https://www.ozon.ru/travel/tours/"


def test_generic_route_failure_keeps_its_source_and_structured_warnings(monkeypatch):
    async def fail(**kwargs):
        raise TimeoutError()

    monkeypatch.setattr(server, "_ozon_package_adapter", SimpleNamespace(search_by_url=fail))
    response = asyncio.run(server.ozon_travel_tours_search(search_url=search_url()))
    assert response.offers == []
    assert response.warnings == ["OZON_TOURS_FAILED_TimeoutError"]
    assert search_context(response.source_url) == search_context(search_url())


def test_url_search_obeys_the_existing_cooldown_before_browser_access(tmp_path):
    access = OzonToursAccess(None, tmp_path / "state.json")
    access.write({"status": "OZON_TOURS_CAPTCHA_REQUIRED", "retry_after": 9999999999})
    adapter = OzonToursAdapter(object(), access)
    response = asyncio.run(adapter.search_by_url(search_url=search_url()))
    assert response["offers"] == []
    assert "CAPTCHA_OR_BLOCKED" in response["warnings"]
    assert response["source_url"] == canonical_search_url(search_url())


def test_generic_url_navigation_keeps_route_and_does_not_visit_unrelated_pages(tmp_path, monkeypatch):
    calls = []
    target = canonical_search_url(search_url())
    current = "https://www.ozon.ru/travel/tours/"

    async def inspect(**kwargs):
        return {"status": "OZON_TOURS_PAGE_AVAILABLE", "browser_tab_id": "retained"}

    adapter = OzonToursAdapter(SimpleNamespace(inspect=inspect, base_url="http://unused"),
                               OzonToursAccess(None, tmp_path / "state.json"))

    async def request(client, path, payload=None):
        nonlocal current
        calls.append((path, payload))
        if path.endswith("/navigate"):
            current = payload["url"]
            return {}
        assert path == "/tabs/retained/evaluate"
        if payload["expression"].startswith("(() => ({url:"):
            return {"result": {"url": current, "html": (FIXTURES / "ozon_tours_search.html").read_text()}}
        return {"result": {"title": "Туры", "text": "Город вылета Ночей Найти туры"}}

    monkeypatch.setattr(adapter, "_request", request)
    response = asyncio.run(adapter.search_by_url(search_url=search_url()))
    assert len(response["offers"]) == 3
    assert response["source_url"] == target
    assert [(path, payload) for path, payload in calls if path.endswith("/navigate")] == [
        ("/tabs/retained/navigate", {"url": target})]
