"""Regression coverage for price, itinerary, and shared browser contracts."""
import asyncio
from pathlib import Path
from types import SimpleNamespace
import time

import httpx
import pytest

from marketplaces_mcp.adapters.ozon_travel import OzonTravelAdapter
from marketplaces_mcp.adapters.ozon_tours import OzonToursAdapter, build_search_url
from marketplaces_mcp.adapters.wildberries import _api_product_to_result
from marketplaces_mcp.core.models import ProductResult
from marketplaces_mcp.core.matching import group_product_results
from marketplaces_mcp.core.ozon_tours_access import OzonToursAccess
from marketplaces_mcp.core.ozon_tours_browser import OzonToursBrowser
from marketplaces_mcp.mcp_server import server

HOTEL_URL = 'https://www.ozon.ru/travel/hotels/product/hotel-volna-1001/'
HOTEL_HEAD = '- heading "Отель Волна, 4*" [level=1]\n- text: 10.05.2030 – 12.05.2030, 2 гостя, 1 номер\n'
ROOM = '- heading "Стандарт с двуспальной кроватью" [level=2]\n'
FLIGHT = '''- article:
  - text: S7 Airlines В пути 1ч 30м 23:30 – 01:00 +1 Прямой Москва, DME – Санкт-Петербург, LED
  - text: Без багажа
  - text: 5 000 ₽
  - button "Выбрать"
'''


def hotel(snapshot):
    return asyncio.run(OzonTravelAdapter().hotel_details(
        HOTEL_URL, destination='Сочи', check_in='2030-05-10', check_out='2030-05-12',
        strategy='fixture', fixture_html=snapshot))


def test_explicit_wrong_hotel_year_cannot_verify_price():
    result, warnings = hotel(HOTEL_HEAD.replace('2030', '2029') + ROOM + '- text: 9 200 ₽\n')
    assert result.total_price is None, (result.total_price, warnings, result.raw['request_context'])


def test_each_tariff_keeps_its_own_meal_and_cancellation():
    snapshot = HOTEL_HEAD + ROOM + '''- text: Завтрак включён
- text: Бесплатная отмена до 8 мая
- text: Оплата в отеле 10 000 ₽
- button "Выбрать"
- text: Без питания
- text: Невозвратный тариф
- text: Оплата сейчас 9 200 ₽
- button "Выбрать"
'''
    result, warnings = hotel(snapshot)
    cheaper = next(rate for rate in result.rates if rate.price == 9200)
    assert cheaper.refundable is False, cheaper.model_dump()
    assert cheaper.meal_plan == 'Без питания'
    assert cheaper.payment_terms == 'Оплата сейчас'


def test_html_room_headings_remain_parseable():
    snapshot = '''<h1>Отель Волна, 4*</h1>
<p>10.05.2030 – 12.05.2030, 2 гостя, 1 номер</p>
<h2>Стандарт с двуспальной кроватью</h2>
<p>9 200 ₽</p><p>Завтрак включён</p><button>Выбрать</button>'''
    result, warnings = hotel(snapshot)
    assert result.total_price == 9200, (result.model_dump(), warnings)


def test_overnight_flight_arrives_next_day():
    offers, warnings, _ = asyncio.run(OzonTravelAdapter().search_flights(
        'MOW', 'LED', '2030-05-10', strategy='fixture', fixture_html=FLIGHT))
    assert offers[0].segments[0].arrival_at == '2030-05-11T01:00:00', offers[0].segments[0].model_dump()


def test_roundtrip_cannot_quote_single_visible_leg_as_complete():
    offers, warnings, _ = asyncio.run(OzonTravelAdapter().search_flights(
        'MOW', 'LED', '2030-05-10', '2030-05-12', strategy='fixture', fixture_html=FLIGHT))
    assert not any(offer.price is not None and offer.availability == 'available' and len(offer.segments) < 2
                   for offer in offers), [offer.model_dump(mode='json') for offer in offers]


def test_roundtrip_dedup_preserves_distinct_return_flights():
    card = '''- article:
  - text: S7 Airlines В пути 1ч 30м 09:30 – 11:00 Прямой Москва, DME – Санкт-Петербург, LED
  - text: S7 Airlines В пути 1ч 30м RETURN_TIME Прямой Санкт-Петербург, LED – Москва, DME
  - text: 10 000 ₽
  - button "Выбрать"
'''
    snapshot = card.replace('RETURN_TIME', '15:00 – 16:30') + card.replace('RETURN_TIME', '20:00 – 21:30')
    offers, _, _ = asyncio.run(OzonTravelAdapter().search_flights(
        'MOW', 'LED', '2030-05-10', '2030-05-12', strategy='fixture', fixture_html=snapshot))
    assert len(offers) == 2, [offer.model_dump(mode='json') for offer in offers]


def test_wildberries_public_api_price_participates_in_comparison(monkeypatch):
    wb = _api_product_to_result({'id': 123, 'name': 'Бумага A4 500 листов',
        'totalQuantity': 10, 'sizes': [{'price': {'product': 30000, 'basic': 50000}}]})
    ozon = ProductResult(marketplace='ozon', title=wb.title,
        url='https://www.ozon.ru/product/paper-1/', price=400, price_kind='exact', availability='available')
    class StaticAdapter:
        def __init__(self, name, offers):
            self.marketplace, self.offers = name, offers
        async def search(self, **kwargs):
            return self.offers, [], 'https://example.test/search'
    monkeypatch.setattr(server, '_adapters', {
        'wildberries': StaticAdapter('wildberries', [wb]),
        'ozon': StaticAdapter('ozon', [ozon]),
        'yandex_market': StaticAdapter('yandex_market', []),
    })
    monkeypatch.setattr(server, 'create_artifact', lambda data: 'review-fixture')
    response = asyncio.run(server.marketplaces_compare('Бумага A4 500 листов', strategy='fixture'))
    assert any(item.marketplace == 'wildberries' for item in response.best_offers), (
        wb.model_dump(), [item.model_dump() for item in response.best_offers], response.warnings)


def test_network_switches_are_not_excluded_as_unidentified_games():
    products = [ProductResult(marketplace=market, title='TP-Link TL-SG108 Network Switch 8 port',
        url=f'https://{market}.example/product', price=3000, price_kind='exact')
        for market in ('ozon', 'yandex_market')]
    groups = group_product_results(products)
    assert len(groups) == 1, [product.game_offer for product in products]


def test_tour_details_respects_existing_captcha_cooldown(tmp_path, monkeypatch):
    url = build_search_url(departure_date='2026-12-19', min_nights=5, max_nights=7, adults=3, child_ages=[0])
    browser = OzonToursBrowser('http://fixture.invalid')
    access = OzonToursAccess(browser, tmp_path / 'state.json')
    access.write({'status': 'OZON_TOURS_CAPTCHA_REQUIRED', 'retry_after': time.time() + 1800})
    adapter = OzonToursAdapter(browser, access)
    fixture_dir = Path(__file__).parent / 'fixtures'
    from urllib.parse import urlencode, urlsplit
    details_url = 'https://www.ozon.ru/travel/tours/hotel?' + urlencode({
        'date': '2026-12-19', 'nights': 5, 'hotelId': 81053, 'searchRawQuery': urlsplit(url).query})
    clicked = []
    async def request(client, path, payload=None):
        if path == '/tabs':
            tabs = [{'tabId': 'search', 'url': url}]
            if clicked:
                tabs.append({'tabId': 'details', 'url': details_url})
            return {'tabs': tabs}
        if path.endswith('/click'):
            clicked.append(path)
            return {}
        raise AssertionError(path)
    async def capture(client, tab_id):
        if tab_id == 'search':
            return {'url': url, 'html': (fixture_dir / 'ozon_tours_search.html').read_text()}
        return {'url': details_url, 'hotel': 'Radisson Blu Resort Fujairah',
                'detail': (fixture_dir / 'ozon_tours_rooms.html').read_text()}
    async def guard(client, tab_id):
        return None
    monkeypatch.setattr(adapter, '_request', request)
    monkeypatch.setattr(adapter, '_capture', capture)
    monkeypatch.setattr(adapter, '_guard', guard)
    response = asyncio.run(adapter.details(search_url=url, hotel_name='Radisson Blu Resort Fujairah'))
    assert clicked == [], (clicked, len(response['offers']), access.read()['status'])


def test_tour_browser_failure_returns_structured_response(monkeypatch):
    async def failed_search(**kwargs):
        raise httpx.ReadTimeout('fixture browser unavailable')
    monkeypatch.setattr(server, '_ozon_package_adapter', SimpleNamespace(search=failed_search))
    response = asyncio.run(server.ozon_travel_tours_search(departure_date='2026-12-19')).model_dump()
    assert response['source_url']
    assert response['offers'] == []
    assert response['warnings']


@pytest.mark.parametrize('displayed', [
    '10.05.2029 – 12.05.2029', '10/05/2029 – 12/05/2029',
    '2029-05-10 – 2029-05-12', '10 мая 2029 – 12 мая 2029', '10 – 12 мая 2029',
])
def test_explicit_date_conflicts_withhold_hotel_prices(displayed):
    snapshot = HOTEL_HEAD.replace('10.05.2030 – 12.05.2030', displayed) + ROOM + '- text: 9 200 ₽\n'
    result, warnings = hotel(snapshot)
    assert result.total_price is None
    assert 'DATE_AVAILABILITY_UNVERIFIED' in warnings


@pytest.mark.parametrize('displayed', [
    '10.05.2030 – 12.05.2030', '10/05 – 12/05', '2030-05-10 – 2030-05-12',
    '10 мая 2030 – 12 мая 2030', '10 – 12 мая 2030', '10 – 12 мая',
])
def test_matching_date_formats_preserve_hotel_prices(displayed):
    result, warnings = hotel(HOTEL_HEAD.replace('10.05.2030 – 12.05.2030', displayed)
                             + ROOM + '- text: 9 200 ₽\n')
    assert result.total_price == 9200
    assert warnings == []


@pytest.mark.parametrize('html', [False, True])
def test_same_price_tariffs_keep_distinct_terms(html):
    if html:
        snapshot = '''<h1>Отель Волна, 4*</h1><p>10 – 12 мая, 2 гостя, 1 номер</p>
<h2>Стандарт с двуспальной кроватью</h2>
<div><p>Завтрак включён Бесплатная отмена Оплата в отеле</p><p>9 200 ₽</p><button>Выбрать</button></div>
<div><p>Без питания Невозвратный тариф Оплата сейчас</p><p>9 200 ₽</p><button>Выбрать</button></div>'''
    else:
        snapshot = HOTEL_HEAD + ROOM + '''- text: 9 200 ₽
- text: Завтрак включён Бесплатная отмена Оплата в отеле
- button "Выбрать"
- text: 9 200 ₽
- text: Без питания Невозвратный тариф Оплата сейчас
- button "Выбрать"
'''
    result, warnings = hotel(snapshot)
    assert warnings == []
    assert len(result.rates) == 2
    assert [rate.refundable for rate in result.rates] == [True, False]
    assert [rate.payment_terms for rate in result.rates] == ['Оплата в отеле', 'Оплата сейчас']


@pytest.mark.parametrize('second_price', ['8 000', '9 200'])
def test_unbounded_tariff_prices_are_not_combined(second_price):
    result, warnings = hotel(HOTEL_HEAD + ROOM + '- text: 9 200 ₽ Бесплатная отмена\n'
                            f'- text: {second_price} ₽ Невозвратный тариф\n')
    assert result.rates == []
    assert result.total_price is None
    assert {'PRICE_UNVERIFIED', 'ROOM_RATES_UNVERIFIED'} <= set(warnings)


@pytest.mark.parametrize(('offset', 'expected'), [
    ('+1', '2030-05-11T01:00:00'), ('(+2)', '2030-05-12T01:00:00'),
    ('-1', '2030-05-09T01:00:00'), ('', None),
])
def test_flight_arrival_day_requires_displayed_evidence(offset, expected):
    offers, warnings, _ = asyncio.run(OzonTravelAdapter().search_flights(
        'MOW', 'LED', '2030-05-10', strategy='fixture', fixture_html=FLIGHT.replace('+1', offset)))
    assert offers[0].segments[0].arrival_at == expected
    assert ('ARRIVAL_DATE_UNVERIFIED' in warnings) == (expected is None)


def test_incomplete_roundtrip_is_explicit_and_identical_cards_are_deduplicated():
    offers, warnings, _ = asyncio.run(OzonTravelAdapter().search_flights(
        'MOW', 'LED', '2030-05-10', '2030-05-12', strategy='fixture', fixture_html=FLIGHT * 2))
    assert len(offers) == 1
    assert offers[0].price is None and offers[0].availability is None
    assert {'PRICE_UNVERIFIED', 'FLIGHT_ITINERARY_UNVERIFIED'} <= set(warnings)


@pytest.mark.parametrize(('variant_prices', 'expected_price', 'kind'), [
    ([30000], 300, 'exact'), ([30000, 30000], 300, 'exact'),
    ([40000, 30000], 300, 'from'),
])
def test_wildberries_variant_prices_are_classified(variant_prices, expected_price, kind):
    from marketplaces_mcp.core.price_evidence import is_public_price
    product = _api_product_to_result({'id': 1, 'name': 'Бумага A4', 'totalQuantity': 5,
        'sizes': [{'price': {'product': price, 'wallet': price - 1000}} for price in variant_prices]})
    assert product.price == expected_price
    assert product.price_kind == kind
    assert is_public_price(product) == (kind == 'exact')


@pytest.mark.parametrize('title', ['TP-Link Network Switch', 'Nintendo Switch 2 Console',
                                    'Консоль Nintendo Switch 2'])
def test_hardware_does_not_receive_game_metadata(title):
    assert ProductResult(marketplace='ozon', title=title, url='https://www.ozon.ru/product/1/').game_offer is None


@pytest.mark.parametrize('title', ['Игра Mario Kart World Switch 2', 'Mario Kart World Nintendo Switch 2',
                                    'Mario Kart World Switch 2 cartridge'])
def test_game_listings_keep_media_matching_guard(title):
    assert ProductResult(marketplace='ozon', title=title, url='https://www.ozon.ru/product/1/').game_offer is not None


@pytest.mark.parametrize('state', ['OZON_TOURS_CAPTCHA_REQUIRED', 'OZON_TOURS_BLOCKED',
                                  'OZON_TOURS_STATE_ERROR', 'OZON_TOURS_PROBE_INTERRUPTED_OR_RUNNING'])
def test_tour_access_gate_precedes_every_browser_request(tmp_path, monkeypatch, state):
    browser = OzonToursBrowser('http://fixture.invalid')
    access = OzonToursAccess(browser, tmp_path / 'state.json')
    access.write({'status': state, 'retry_after': time.time() + 1800})
    adapter = OzonToursAdapter(browser, access)
    async def unexpected(*args, **kwargs):
        pytest.fail('Browser request during shared cooldown')
    monkeypatch.setattr(browser, 'inspect', unexpected)
    monkeypatch.setattr(adapter, '_request', unexpected)
    url = build_search_url(departure_date='2026-12-19')
    for result in (asyncio.run(adapter.search(departure_date='2026-12-19')),
                   asyncio.run(adapter.details(search_url=url, hotel_name='Fixture'))):
        assert result['offers'] == []
        assert result['source_url'] == url
        assert state in result['warnings']


@pytest.mark.parametrize('error', [httpx.ReadTimeout('test'), TimeoutError(), BlockingIOError(),
                                  ValueError('OZON_TOURS_CAPTCHA_REQUIRED'), ValueError('wrong hotel')])
@pytest.mark.parametrize('operation', ['search', 'details'])
def test_tour_operational_errors_keep_structured_contract(tmp_path, monkeypatch, error, operation):
    async def failed(**kwargs):
        raise error
    access = OzonToursAccess(None, tmp_path / 'state.json')
    monkeypatch.setattr(server, '_tours_access', access)
    monkeypatch.setattr(server, '_ozon_package_adapter', SimpleNamespace(search=failed, details=failed))
    url = build_search_url(departure_date='2026-12-19')
    call = (server.ozon_travel_tours_search(departure_date='2026-12-19') if operation == 'search'
            else server.ozon_travel_tour_details(search_url=url, hotel_name='Fixture'))
    result = asyncio.run(call)
    assert result.source_url == url and result.offers == [] and result.warnings
    if str(error) == 'OZON_TOURS_CAPTCHA_REQUIRED':
        assert 'CAPTCHA_OR_BLOCKED' in result.warnings


def test_tour_tool_cancellation_propagates(monkeypatch):
    async def cancel(**kwargs):
        raise asyncio.CancelledError()
    monkeypatch.setattr(server, '_ozon_package_adapter', SimpleNamespace(search=cancel))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(server.ozon_travel_tours_search(departure_date='2026-12-19'))


def test_busy_tour_lock_returns_structured_response(tmp_path, monkeypatch):
    access = OzonToursAccess(None, tmp_path / 'state.json')
    adapter = OzonToursAdapter(OzonToursBrowser('http://fixture.invalid'), access)
    monkeypatch.setattr(server, '_tours_access', access)
    monkeypatch.setattr(server, '_ozon_package_adapter', adapter)
    with adapter._lock():
        result = asyncio.run(server.ozon_travel_tours_search(departure_date='2026-12-19'))
    assert result.offers == []
    assert result.warnings == ['OZON_TOURS_REQUEST_IN_PROGRESS']


@pytest.mark.parametrize('payload', [
    {'retry_after': 0}, {'status': 'OZON_TOURS_PAGE_AVAILABLE', 'retry_after': float('nan')},
    {'status': 'OZON_TOURS_PAGE_AVAILABLE', 'retry_after': True},
])
def test_invalid_tour_state_stops_navigation(tmp_path, payload):
    import json
    path = tmp_path / 'state.json'
    path.write_text(json.dumps(payload))
    access = OzonToursAccess(None, path)
    assert access.read()['status'] == 'OZON_TOURS_STATE_ERROR'
    assert access.navigation_blocked()


@pytest.mark.parametrize('html', [False, True])
def test_hotel_heading_alone_cannot_become_a_room(html):
    snapshot = ('<h1>Radisson Blu Resort</h1><p>10 – 12 мая, 2 гостя, 1 номер</p><p>9 200 ₽</p>'
                if html else '- heading "Radisson Blu Resort" [level=1]\n'
                '- text: 10 – 12 мая, 2 гостя, 1 номер\n- text: 9 200 ₽')
    result, _ = hotel(snapshot)
    assert result.rates == []


def test_initial_tour_challenge_is_persisted_for_other_calls(tmp_path, monkeypatch):
    browser = OzonToursBrowser('http://fixture.invalid')
    access = OzonToursAccess(browser, tmp_path / 'state.json')
    adapter = OzonToursAdapter(browser, access)
    calls = []
    async def inspect(**kwargs):
        calls.append(kwargs)
        return {'status': 'OZON_TOURS_CAPTCHA_REQUIRED', 'browser_tab_id': 'kept'}
    monkeypatch.setattr(browser, 'inspect', inspect)
    first = asyncio.run(adapter.search(departure_date='2026-12-19'))
    second = asyncio.run(adapter.search(departure_date='2026-12-19'))
    assert len(calls) == 1
    assert first['offers'] == second['offers'] == []
    assert not access.read()['retry_allowed']
    assert 'CAPTCHA_OR_BLOCKED' in second['warnings']


@pytest.mark.parametrize('kind', ['search', 'details'])
def test_tour_successes_validate_against_core_models(monkeypatch, kind):
    from urllib.parse import urlencode, urlsplit
    from marketplaces_mcp.adapters.ozon_tours import parse_leads, parse_rates
    from marketplaces_mcp.core.models import OzonTourLead, OzonTourRate
    url = build_search_url(departure_date='2026-12-19', min_nights=5, max_nights=7,
                           adults=3, child_ages=[0])
    fixtures = Path(__file__).parent / 'fixtures'
    if kind == 'search':
        offers = parse_leads({'url': url, 'html': (fixtures / 'ozon_tours_search.html').read_text()}, url)
    else:
        detail_url = 'https://www.ozon.ru/travel/tours/hotel?' + urlencode({
            'date': '2026-12-19', 'searchRawQuery': urlsplit(url).query})
        offers = parse_rates({'url': detail_url, 'hotel': 'Radisson Blu Resort Fujairah',
                              'detail': (fixtures / 'ozon_tours_rooms.html').read_text()},
                             url, 'Radisson Blu Resort Fujairah')
    async def success(**kwargs):
        return {'source_url': url, 'offers': offers, 'warnings': []}
    monkeypatch.setattr(server, '_ozon_package_adapter', SimpleNamespace(search=success, details=success))
    call = (server.ozon_travel_tours_search(departure_date='2026-12-19', min_nights=5,
                                          max_nights=7, adults=3, child_ages=[0]) if kind == 'search'
            else server.ozon_travel_tour_details(search_url=url, hotel_name='Radisson Blu Resort Fujairah'))
    result = asyncio.run(call)
    assert len(result.offers) == len(offers) > 0
    assert not result.warnings
    assert isinstance(result.offers[0], OzonTourLead if kind == 'search' else OzonTourRate)
