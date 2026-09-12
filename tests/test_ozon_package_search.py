from pathlib import Path
from urllib.parse import urlencode, urlsplit

import pytest

from marketplaces_mcp.adapters.ozon_tours import build_search_url, parse_leads, parse_rates, search_context

FIXTURES = Path(__file__).parent / "fixtures"
URL = build_search_url(departure_date="2026-12-19", min_nights=5, max_nights=7, adults=3, child_ages=[0])
HOTEL = "Radisson Blu Resort Fujairah"


def detail():
    return {"url": "https://www.ozon.ru/travel/tours/hotel?" + urlencode({
        "date": "2026-12-19", "nights": 5, "hotelId": 81053,
        "searchRawQuery": urlsplit(URL).query}), "hotel": HOTEL,
        "detail": (FIXTURES / "ozon_tours_rooms.html").read_text()}


def test_observed_search_contract_preserves_infant_zero():
    query = search_context(URL)
    assert query["Children"] == "0" and query["Dlts"] == "3"
    assert query["fromCity"] == "140212000" and query["toCountry"] == "210915000"
    assert query["mealTypes"] == "ozon_ai,ozon_aip,ozon_sai,ozon_uai"
    assert "dayRound" not in URL


def test_search_cards_never_mislabel_breakfast_as_all_inclusive():
    data = {"url": URL, "html": (FIXTURES / "ozon_tours_search.html").read_text()}
    offers = parse_leads(data, URL)
    assert len(offers) == 3
    assert all(x["total_price"] is None and x["meal_plan"] is None for x in offers)


def test_live_room_structure_filters_meal_and_requires_explicit_flight():
    offers = parse_rates(detail(), URL, HOTEL)
    assert len(offers) == 12
    assert {x["room_name"] for x in offers} == {"Стандартный номер", "Улучшенный номер"}
    assert offers[0]["total_price"] == 311787
    assert all(x["meal_plan"] != "Завтрак" for x in offers)
    assert all(x["flight_included"] and x["flight_selection_pending"] for x in offers)
    assert all(x["adults"] == 3 and x["child_ages"] == [0] and x["rooms"] == 1 for x in offers)
    assert all(x["stay_end_date"] == "2026-12-24" and x["return_date"] is None and x["nights"] == 5 for x in offers)
    assert {x["meal_plan"] for x in offers} == {"Всё включено", "Ультра всё включено", "Всё включено с ограничениями"}


@pytest.mark.parametrize("kwargs", [{"rooms": 2}, {"child_ages": [17]}, {"child_ages": [True]},
                                    {"min_nights": 5, "max_nights": 12}, {"adults": 0},
                                    {"origin": "MOW"}, {"destination": "Дубай"}])
def test_unsupported_inputs_fail_before_browser_request(kwargs):
    with pytest.raises(ValueError):
        build_search_url(departure_date="2026-12-19", **kwargs)


@pytest.mark.parametrize("field,value", [("Children", "2"), ("Dlts", "2"),
                                         ("startDate", "2026-12-18"), ("fromCity", "140158000")])
def test_wrong_party_date_or_origin_cannot_produce_quotes(field, value):
    d = detail()
    changed = search_context(URL) | {field: value}
    d["url"] = "https://www.ozon.ru/travel/tours/hotel?" + urlencode({
        "date": "2026-12-19", "searchRawQuery": urlencode(changed)})
    with pytest.raises(ValueError):
        parse_rates(d, URL, HOTEL)


def test_hotel_and_selected_date_must_match():
    d = detail()
    with pytest.raises(ValueError):
        parse_rates(d | {"hotel": "Other hotel"}, URL, HOTEL)
    with pytest.raises(ValueError):
        parse_rates(d | {"url": d["url"].replace("date=2026-12-19", "date=2026-12-20")}, URL, HOTEL)


def test_hotel_only_or_wrong_return_date_rows_are_rejected():
    d = detail()
    for html in (d["detail"].replace("перелётом", "проживанием"),
                 d["detail"].replace("до 24.12", "до 25.12")):
        assert parse_rates(d | {"detail": html}, URL, HOTEL) == []


def test_recommendation_price_outside_room_widget_never_becomes_package():
    d = detail() | {"detail": '<h1>Hotel</h1><p>Всё включено 1 ₽ тур с перелётом</p>'}
    assert parse_rates(d, URL, HOTEL) == []
