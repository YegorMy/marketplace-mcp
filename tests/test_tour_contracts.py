import asyncio
from datetime import date
from urllib.parse import parse_qs

import httpx
import pytest

from marketplaces_mcp.adapters.package_tours import PackageToursAdapter
from marketplaces_mcp.core.ozon_tours_access import OzonToursAccess, classify_page


def sample():
    return dict(price_all="300000", hotelNights=5, hotel_name="Fixture resort",
                sd_s_full="19.12.2026", sd_e_full="24.12.2026", Country=11,
                fromcity_id=3, tour="//www.1001tur.ru/tourdesc/oae/fixture/abc/",
                currency="RUB", hotel_cat=5, food_name="всё включено",
                food_name_ruspo="AI", adults=3, kids=1, infants=1, kidsAge=[1],
                ticket_include=1, hotel_stop="N")


def run_batch(raw):
    async def run():
        def respond(request):
            query = parse_qs(request.url.query.decode())
            assert query["ticket_include"] == ["1"]
            assert query["flight_type"] == ["any"]
            assert query["kidsAge"] == ["1"]
            return httpx.Response(200, json={"tourlist": raw})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await PackageToursAdapter()._search_one(
                client, country_name="ОАЭ", country_id="11", origin_name="Санкт-Петербург",
                origin_id="3", start=date(2026, 12, 19), end=date(2026, 12, 19),
                nights=5, adults=3, children=0, infants=1, kid_ages=[1],
                all_inclusive_only=True, stars=[4, 5],
            )
    return asyncio.run(run())


def test_package_is_flight_included_and_total_not_person_or_night_price():
    offers, warnings = run_batch([sample()])
    assert not warnings
    assert offers[0].flight_included is True
    assert offers[0].total_price == 300000
    assert offers[0].price_per_night == 60000
    assert offers[0].availability == "quoted_not_booked"


@pytest.mark.parametrize("changes", [
    {"ticket_include": 0}, {"ticket_include": None}, {"kidsAge": [2]},
    {"adults": 2}, {"infants": 0}, {"Country": 4}, {"fromcity_id": 1},
    {"hotelNights": 7}, {"sd_s_full": "18.12.2026"}, {"currency": "USD"},
    {"food_name": "завтрак", "food_name_ruspo": "BB"}, {"hotel_stop": "Y"},
    {"tour": "https://evil.test/tourdesc/x"}, {"price_all": "0"},
    {"sd_s_full": "not-a-date"}, {"hotelNights": "garbage"},
])
def test_wrong_context_and_hotel_only_offers_cannot_rank(changes):
    raw = sample() | changes
    offers, warnings = run_batch([raw, sample()])
    assert len(offers) == 1
    assert "UNVERIFIED_OR_MISMATCHED_OFFERS_EXCLUDED" in warnings


def test_flight_variant_is_found_inside_hotel_only_parent():
    raw = sample() | {"ticket_include": 0, "tour_by_hotel": [sample()]}
    assert len(run_batch([raw])[0]) == 1


def test_request_rejects_unknown_child_ages_and_multiple_rooms_before_network():
    base = dict(origin="LED", destination="ОАЭ", departure_date_from="2026-12-19",
                departure_date_to="2026-12-19", min_nights=5, max_nights=5, adults=3)
    for kwargs in ({"children": 1}, {"rooms": 2}, {"infants": 1, "infant_ages": [4]}):
        with pytest.raises(ValueError):
            asyncio.run(PackageToursAdapter().search(**base, **kwargs))


def test_ozon_access_is_separate_from_search_and_cached_across_instances(tmp_path):
    calls = []
    async def probe(url):
        calls.append(url)
        return '<h1>Похоже, нет соединения</h1><p>Выключите VPN</p>'
    path = tmp_path / "access.json"
    a = OzonToursAccess(probe, path)
    assert asyncio.run(a.status())["status"] == "OZON_TOURS_NOT_CHECKED"
    assert not calls
    first = asyncio.run(a.status(probe=True))
    second = asyncio.run(OzonToursAccess(probe, path).status(probe=True))
    assert first["status"] == "OZON_TOURS_BLOCKED" and first["search_supported"]
    assert second["cached"] and len(calls) == 1
    assert path.stat().st_mode & 0o777 == 0o600


def test_incidental_block_words_do_not_hide_available_form():
    page = '<h1>Туры</h1><p>Город вылета Ночей Найти туры</p><script>cloudflare captcha</script>'
    assert classify_page(page) == "OZON_TOURS_PAGE_AVAILABLE"


def test_corrupt_access_state_never_triggers_live_probe(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("broken")
    async def forbidden(url):
        raise AssertionError("must not navigate")
    state = asyncio.run(OzonToursAccess(forbidden, path).status(probe=True))
    assert state["status"] == "OZON_TOURS_STATE_ERROR" and not state["retry_allowed"]


def test_cancellation_preserves_cooldown_and_releases_lock(tmp_path):
    path = tmp_path / "state.json"
    async def cancel(url):
        raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(OzonToursAccess(cancel, path).status(probe=True))
    state = asyncio.run(OzonToursAccess(cancel, path).status(probe=True))
    assert state["cached"] and not state["retry_allowed"]
