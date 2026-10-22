"""Regressions for airport-specific flight discovery after a blocked search."""
import asyncio
from datetime import date
from urllib.parse import parse_qs, urlsplit

import pytest

from marketplaces_mcp.adapters import OzonTravelAdapter
from marketplaces_mcp.core.config import Settings
from marketplaces_mcp.mcp_server import server

PULKOVO = "https://www.ozon.ru/travel/flight/pulkovo-led/dubay-mezhdunarodnyy-dxb/"
SHEREMETYEVO = "https://www.ozon.ru/travel/flight/sheremetevo-svo/dubay-mezhdunarodnyy-dxb/"


def test_blocked_request_does_not_mislabel_a_pulkovo_link_as_svo(monkeypatch):
    adapter = OzonTravelAdapter(Settings(camofox_url=""))

    async def blocked(*args, **kwargs):
        return '<h1>Доступ ограничен</h1>', []

    async def index(*args):
        return [{"href": PULKOVO, "title": "Санкт-Петербург — Дубай"}], None

    monkeypatch.setattr(adapter, "_load_html", blocked)
    monkeypatch.setattr(adapter, "_ddgs", index)
    monkeypatch.setattr(server, "_travel_adapter", adapter)
    monkeypatch.setattr(server, "create_artifact", lambda data: "fixture")
    response = asyncio.run(server.ozon_travel_flights_search(
        "SVO", "DXB", "2030-05-10", adults=2, limit=5))
    assert response.results == []
    assert "CAPTCHA_OR_BLOCKED" in response.warnings
    assert "INDEX_ROUTE_UNVERIFIED" in response.warnings
    assert response.adults == 2 and response.departure_date == date(2030, 5, 10)
    query = parse_qs(urlsplit(response.source_url).query)
    assert query["route"] == ["svodxb"] and query["Dlts"] == ["2"]
    assert query["dates"] == ["d2030-05-10"]


@pytest.mark.parametrize("url", [
    PULKOVO, SHEREMETYEVO.replace("sheremetevo-svo", "moskva-mow"),
    SHEREMETYEVO.replace("-dxb/", "-dwc/"),
    "https://www.ozon.ru/travel/flight/dubay-dxb/sheremetevo-svo/",
    "https://www.ozon.ru/travel/flight/sheremetevo-svo/uae-ae/",
    "https://www.ozon.ru/travel/flight/search?route=svodxb",
    SHEREMETYEVO.replace("www.ozon.ru", "fakeozon.ru"),
    SHEREMETYEVO.replace("www.ozon.ru", "user@www.ozon.ru"),
    "https://[invalid",
])
def test_discovery_skips_wrong_or_unverifiable_routes(monkeypatch, url):
    adapter = OzonTravelAdapter()

    async def index(*args):
        return [{"href": url, "title": "Unverified hit"},
                {"href": SHEREMETYEVO, "title": "Matching indexed route"}], None

    monkeypatch.setattr(adapter, "_ddgs", index)
    offers, warnings = asyncio.run(adapter._discover_flight_route(
        "SVO", "DXB", date(2030, 5, 10), None, limit=5))
    assert len(offers) == 1 and offers[0].url == SHEREMETYEVO
    assert offers[0].raw["title"] == "Matching indexed route"
    assert offers[0].price is None and offers[0].segments == []
    assert {"INDEX_DISCOVERY_ONLY", "PRICE_UNVERIFIED", "DATE_AVAILABILITY_UNVERIFIED"} <= set(warnings)


def test_discovery_uses_resolved_codes_for_city_name_requests(monkeypatch):
    adapter = OzonTravelAdapter(Settings(camofox_url=""))
    queries = []

    async def blocked(*args, **kwargs):
        return None, ["CAPTCHA_OR_BLOCKED"]

    async def index(query, limit):
        queries.append(query)
        return [{"href": SHEREMETYEVO.replace("sheremetevo-svo", "moskva-mow")}], None

    monkeypatch.setattr(adapter, "_load_travel_page", blocked)
    monkeypatch.setattr(adapter, "_ddgs", index)
    offers, _, _ = asyncio.run(adapter.search_flights("Москва", "Дубай", "2030-05-10", adults=2))
    assert queries == ["site:ozon.ru/travel/flight MOW DXB авиабилеты"]
    assert offers[0].origin == "MOW" and offers[0].destination == "DXB"


@pytest.mark.parametrize("page,warnings", [
    ("<h1>Доступ ограничен</h1>", []), (None, ["CAPTCHA_OR_BLOCKED"]),
])
def test_visible_block_does_not_open_a_fallback_browser(monkeypatch, page, warnings):
    adapter = OzonTravelAdapter(Settings(camofox_url="http://unused"))
    fallback_calls = []

    async def load(*args, **kwargs):
        return page, warnings

    async def fallback(*args):
        fallback_calls.append(True)
        return "<p>Do not use a second browser after a block</p>"

    monkeypatch.setattr(adapter, "_load_html", load)
    monkeypatch.setattr(adapter, "_fetch_with_camofox", fallback)
    html, returned_warnings = asyncio.run(adapter._load_travel_page(
        SHEREMETYEVO, strategy="auto", fixture_html=None, fixture_key="unused"))
    assert html is None
    assert "CAPTCHA_OR_BLOCKED" in returned_warnings
    assert fallback_calls == []


def test_browser_fallback_remains_available_for_a_transport_failure(monkeypatch):
    adapter = OzonTravelAdapter(Settings(camofox_url="http://unused"))

    async def load(*args, **kwargs):
        return None, ["HIVE_WEB_FAILED"]

    async def fallback(*args):
        return "<p>Flight search loaded</p>"

    monkeypatch.setattr(adapter, "_load_html", load)
    monkeypatch.setattr(adapter, "_fetch_with_camofox", fallback)
    html, warnings = asyncio.run(adapter._load_travel_page(
        SHEREMETYEVO, strategy="auto", fixture_html=None, fixture_key="unused"))
    assert html == "<p>Flight search loaded</p>"
    assert "CAMOFOX_FALLBACK" in warnings
