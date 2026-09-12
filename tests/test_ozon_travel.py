from __future__ import annotations

import asyncio
from datetime import date

from marketplaces_mcp.adapters import OzonTravelAdapter

FLIGHT_RESULTS_HTML = """
<html><body>
  <article>
    <div>Победа</div>
    <div>07:35 — 09:05</div>
    <div>Прямой 1ч 30м</div>
    <div>Внуково, Москва — Пулково, Санкт-Петербург</div>
    <div>Без багажа</div>
    <a href="/travel/flight/search/mowled/d2030-05-10">от 2 679 ₽</a>
  </article>
  <article>
    <div>Аэрофлот</div>
    <div>10:20 — 12:00</div>
    <div>Прямой 1ч 40м</div>
    <div>Шереметьево, Москва — Пулково, Санкт-Петербург</div>
    <div>Багаж 23 кг</div>
    <a href="/travel/flight/search/mowled/d2030-05-10">от 4 120 ₽</a>
  </article>
</body></html>
"""


FLIGHT_RESULTS_SNAPSHOT = """
- article:
  - list:
    - listitem: Самый дешёвый
  - text: S7 Airlines В пути 1ч 35м 09:30 – 11:05 Прямой Москва, DME – Санкт-Петербург, LED
  - button "Детали перелета" [e47]
  - text: 23 + 1 959 ₽
  - text: + 52 5 168 ₽ 5 441 ₽
  - button "Выбрать" [e48]
- article:
  - text: Аэрофлот, рейс выполняет Россия В пути 1ч 30м 11:30 – 13:00 Прямой Москва, VKO – Санкт-Петербург, LED
  - button "Детали перелета" [e53]
  - text: Без багажа
  - text: + 61 6 131 ₽ 6 191 ₽
  - button "Выбрать" [e54]
"""

ROUND_TRIP_FLIGHT_SNAPSHOT = """
- article:
  - list:
    - listitem: Самый дешёвый
  - text: S7 Airlines В пути 1ч 35м 09:30 – 11:05 Прямой Москва, DME – Санкт-Петербург, LED
  - text: S7 Airlines В пути 1ч 35м 20:40 – 22:15 Прямой Санкт-Петербург, LED – Москва, DME
  - text: X Без багажа
  - text: 23 + 4 212 ₽
  - text: + 106 10 589 ₽ 11 032 ₽
  - button "Выбрать"
"""


HOTEL_RESULTS_HTML = """
<html><body>
  <div>10 – 12 мая, 2 гостя, 1 номер</div>
  <article>
    <a href="/travel/hotels/product/hotel-volna-1001/"><h2>Отель Волна, 4*</h2></a>
    <div>Сочи, улица Морская, 1 • 900 м до центра</div>
    <div>4.8 250 отзывов Wi-Fi Парковка Бассейн</div>
    <div>от 5 000 ₽</div>
  </article>
  <article>
    <a href="/travel/hotels/product/hotel-bereg-1002/"><h2>Отель Берег, 3*</h2></a>
    <div>Сочи, улица Южная, 7 • 2.1 км до центра</div>
    <div>4.6 90 отзывов Wi-Fi Кондиционер</div>
    <div>от 3 200 ₽</div>
  </article>
</body></html>
"""


HOTEL_DETAILS_SNAPSHOT = """
- heading "Отель Волна, 4*" [level=1]
- text: 10 – 12 мая, 2 гостя, 1 номер
- text: 4.8 250 отзывов
- text: Сочи, улица Морская, 1 • 900 м до центра
- text: Wi-Fi Парковка Бассейн Ресторан
- heading "Стандарт с двуспальной кроватью" [level=2]
- text: 9 200 ₽
- text: Завтрак включён Бесплатная отмена до 8 мая Оплата сейчас Остался 1 вариант
- text: Другой тариф: нет мест
- heading "Люкс с видом на море" [level=2]
- text: 14 000 ₽
- text: Без питания Невозвратный тариф Оплата сейчас
"""


HOTEL_DETAILS_WITH_NEARBY_PRICES = """
- heading "Отель Гарден Хиллс by Provence, 3*" [level=1]
- text: 2 гостя, 1 номер
- text: Ближайшие доступные даты 3 – 5 октября от 3 100 ₽ Ваши даты 10 – 12 октября от 4 840 ₽
- heading "Эконом двухместный" [level=2]
- text: Двуспальная кровать
- text: от 4 142 ₽ 10 – 12 октября, 2 ночи
- text: 2 гостя
Похожие отели и квартиры рядом на 10 – 12 октября
- text: 2 000 ₽
- link "Чужой соседний отель"
"""


HOTEL_DETAILS_WITH_UI_NOISE = """
- heading "Парк-отель Триумф" [level=1]
- text: 9 окт. – 11 окт., 4 гостя, 1 номер
- text: Ближайшие доступные даты 7 – 9 октября от 18 000 ₽
- text: Ваши даты 9 окт. – 11 окт. от 22 000 ₽
- text: Войти
- text: + 724 ₽
- text: Остался 1 вариант
- heading "Семейный номер" [level=2]
- text: 24 000 ₽
- text: Завтрак включён Бесплатная отмена Оплата сейчас Остался 1 вариант
"""


HOTEL_DETAILS_PENDING_SNAPSHOT = """
- heading "Отель Триумф, 4*" [level=1]
- text: Ваши даты пт-вс 9 – 11 октября от 52 000 ₽
- text: Выберите номер
- img "Стандартный двухместный номер с раздельными кроватями №2"
- text: +17 Стандартный двухместный номер с раздельными кроватями №2
- button "Подробнее"
- text: ･ Две односпальные кровати ･ 2 основных, 2 дополнительных места
- text: 1 комната
- text: Мало подходящих вариантов? Для 4 и более взрослых гостей лучше искать несколько номеров — так выбор больше от 46 524 ₽ 9 – 11 октября, 2 ночи
- text: 4 гостя
- button "Показать номера"
"""


HOTEL_DETAILS_LIVE_RATES_SNAPSHOT = """
- heading "Отель Триумф, 4*" [level=1]
- text: Центр города 4.7 км
- text: Почти распродано
- text: Ваши даты пт-вс 9 – 11 октября от 52 000 ₽
- text: Выберите номер Бесплатная отмена Завтрак Две односпальные кровати Двуспальная кровать
- img "Малый коттедж с двумя спальнями (1 двуспальная и 2 односпальные кровати) и сауной Черника, Ландыш, Клевер"
- img "Малый коттедж с двумя спальнями (1 двуспальная и 2 односпальные кровати) и сауной Черника, Ландыш, Клевер"
- img "Малый коттедж с двумя спальнями (1 двуспальная и 2 односпальные кровати) и сауной Черника, Ландыш, Клевер"
- img "Малый коттедж с двумя спальнями (1 двуспальная и 2 односпальные кровати) и сауной Черника, Ландыш, Клевер"
- img "Малый коттедж с двумя спальнями (1 двуспальная и 2 односпальные кровати) и сауной Черника, Ландыш, Клевер"
- img "Малый коттедж с двумя спальнями (1 двуспальная и 2 односпальные кровати) и сауной Черника, Ландыш, Клевер"
- text: +13 Малый коттедж с двумя спальнями (1 двуспальная и 2 односпальные кровати) и сауной Черника, Ландыш, Клевер
- button "Подробнее" [e13]
- text: ･ Две односпальные кровати ･ 2 основных, 2 дополнительных места
- text: 2 комнаты
- text: 70м2 Ванная комната в номере Wi-Fi Вид на окрестности
- text: Душ Фен Полотенца Туалетные принадлежности
- text: Телевизор Холодильник Чайник
- text: Шкаф Рабочий стол Отдельный вход
- text: Завтрак
- text: Бесплатная отмена до 8 окт.
- text: Оплата сейчас 52 000 ₽
- text: + 520
- button "Выбрать" [e15]
- text: Осталось 2 варианта
- img "Малый коттедж с двумя спальнями (1 двуспальная и 2 односпальные кровати) и сауной Брусника"
- text: +13 Малый коттедж с двумя спальнями (1 двуспальная и 2 односпальные кровати) и сауной Брусника
- button "Подробнее" [e16]
- text: 4 основных места
- text: 2 комнаты
- text: Завтрак
- text: Бесплатная отмена до 9 окт.
- text: Оплата сейчас 52 000 ₽
- text: + 520
- button "Выбрать" [e17]
- text: Мало подходящих вариантов? Для 4 и более взрослых гостей лучше искать несколько номеров — так выбор больше от 52 000 ₽ 9 – 11 октября, 2 ночи
- text: 4 гостя
- button "Показать 5 номеров" [e28]
- heading "Похожие отели и квартиры рядом" [level=2]
- link "Sorola Village Park Hotel"
- text: 5.9 км до центра
"""


def test_flight_fixture_parsing_and_sorting():
    async def run():
        return await OzonTravelAdapter().search_flights(
            "MOW",
            "LED",
            "2030-05-10",
            adults=2,
            direct_only=True,
            strategy="fixture",
            fixture_html=FLIGHT_RESULTS_HTML,
        )

    results, warnings, source_url = asyncio.run(run())

    assert warnings == []
    assert source_url == (
        "https://www.ozon.ru/travel/flight/search?Children=0&Dlts=2&Infants=0"
        "&ServiceClass=ECONOMY&dates=d2030-05-10&route=mowled"
    )
    assert [item.price for item in results] == [2679.0, 4120.0]
    assert results[0].origin == "MOW"
    assert results[0].destination == "LED"
    assert results[0].stops == 0
    assert results[0].duration_minutes == 90
    assert results[0].baggage == "not_included"
    assert results[1].baggage == "Багаж 23 кг"


def test_flight_snapshot_keeps_offer_boundaries_and_public_price():
    results = OzonTravelAdapter().parse_flight_results(
        FLIGHT_RESULTS_SNAPSHOT,
        source_url="https://www.ozon.ru/travel/flight/search?route=mowled",
        origin="MOW",
        destination="LED",
        departure_date=date(2030, 5, 10),
        return_date=None,
    )

    assert [item.price for item in results] == [5441.0, 6191.0]
    assert results[0].airlines == ["S7 Airlines"]
    assert results[0].duration_minutes == 95
    assert results[0].stops == 0
    assert results[1].airlines == ["Аэрофлот"]
    assert results[1].baggage == "not_included"


def test_round_trip_url_and_snapshot_keep_both_segments():
    adapter = OzonTravelAdapter()
    source_url = adapter.build_flight_url(
        "MOW",
        "LED",
        date(2030, 5, 10),
        date(2030, 5, 12),
        adults=1,
        children=0,
        infants=0,
        cabin_class="economy",
    )

    assert source_url == (
        "https://www.ozon.ru/travel/flight/search?Children=0&Dlts=1&Infants=0"
        "&ServiceClass=ECONOMY&dates=d2030-05-10d2030-05-12"
        "&route=mowledledmow"
    )

    results = adapter.parse_flight_results(
        ROUND_TRIP_FLIGHT_SNAPSHOT,
        source_url=source_url,
        origin="MOW",
        destination="LED",
        departure_date=date(2030, 5, 10),
        return_date=date(2030, 5, 12),
    )

    assert len(results) == 1
    assert results[0].price == 11032.0
    assert results[0].duration_minutes == 190
    assert results[0].stops == 0
    assert results[0].airlines == ["S7 Airlines"]
    assert [segment.origin for segment in results[0].segments] == ["MOW", "LED"]
    assert [segment.destination for segment in results[0].segments] == ["LED", "MOW"]
    assert results[0].segments[1].departure_at == "2030-05-12T20:40:00"


def test_flight_camofox_loading_marker_is_polled():
    adapter = OzonTravelAdapter()

    assert adapter.camofox_snapshot_attempts == 6
    assert adapter._camofox_snapshot_pending("- paragraph: Получаем расписание рейсов")
    assert not adapter._camofox_snapshot_pending("- article:\n  - text: S7 Airlines")
    assert adapter._camofox_snapshot_pending(HOTEL_DETAILS_PENDING_SNAPSHOT)
    assert not adapter._camofox_snapshot_pending(HOTEL_DETAILS_WITH_UI_NOISE)


def test_hotel_search_keeps_nightly_and_total_prices_separate():
    async def run():
        return await OzonTravelAdapter().search_hotels(
            "Сочи",
            "2030-05-10",
            "2030-05-12",
            sort="price",
            include_rates=False,
            strategy="fixture",
            fixture_html=HOTEL_RESULTS_HTML,
        )

    results, warnings, source_url = asyncio.run(run())

    assert warnings == []
    assert "checkIn=2030-05-10" in source_url
    assert [item.title for item in results] == ["Отель Берег, 3*", "Отель Волна, 4*"]
    assert results[0].total_price is None
    assert results[0].nightly_price == 3200.0
    assert results[0].nights == 2
    assert results[0].stars == 3
    assert results[0].rating == 4.6
    assert results[0].reviews_count == 90


def test_hotel_urls_replace_conflicting_context_and_use_dlts():
    adapter = OzonTravelAdapter()

    search_url = asyncio.run(
        adapter.build_hotel_url(
            "https://www.ozon.ru/travel/hotels/category/sochi/"
            "?adults=2&Dlts=3&checkIn=2025-01-01&checkOut=2025-01-02"
            "&rooms=2&guests=8&keep=yes",
            date(2030, 5, 10),
            date(2030, 5, 12),
            adults=4,
            rooms=1,
            sort="price",
            strategy="fixture",
        )
    )

    assert "Dlts=4" in search_url
    assert "adults=" not in search_url
    assert "checkIn=2030-05-10" in search_url
    assert "checkOut=2030-05-12" in search_url
    assert "rooms=1" in search_url
    assert "guests=" not in search_url
    assert "keep=yes" in search_url


def test_hotel_details_url_replaces_conflicting_context(monkeypatch):
    loaded_urls = []

    async def load(url, **_kwargs):
        loaded_urls.append(url)
        return HOTEL_DETAILS_WITH_UI_NOISE, []

    adapter = OzonTravelAdapter()
    monkeypatch.setattr(adapter, "_load_travel_page", load)
    hotel, warnings = asyncio.run(
        adapter.hotel_details(
            "https://www.ozon.ru/travel/hotels/product/park-otel-tri-umf-1781354057/"
            "?adults=2&Dlts=3&checkIn=2025-01-01&rooms=2",
            destination="Москва",
            check_in="2030-10-09",
            check_out="2030-10-11",
            adults=4,
            rooms=1,
        )
    )

    assert warnings == []
    assert hotel is not None
    assert "Dlts=4" in loaded_urls[0]
    assert "adults=" not in loaded_urls[0]
    assert "Dlts=3" not in loaded_urls[0]
    assert "checkIn=2030-10-09" in loaded_urls[0]
    assert "rooms=1" in loaded_urls[0]
    assert "showAll=true" in loaded_urls[0]


def test_hotel_details_extracts_dated_rates_and_lowest_total():
    async def run():
        return await OzonTravelAdapter().hotel_details(
            "https://www.ozon.ru/travel/hotels/product/hotel-volna-1001/",
            destination="Сочи",
            check_in="2030-05-10",
            check_out="2030-05-12",
            strategy="fixture",
            fixture_html=HOTEL_DETAILS_SNAPSHOT,
        )

    hotel, warnings = asyncio.run(run())

    assert warnings == []
    assert hotel is not None
    assert hotel.title == "Отель Волна, 4*"
    assert hotel.check_in == date(2030, 5, 10)
    assert hotel.check_out == date(2030, 5, 12)
    assert hotel.nights == 2
    assert hotel.total_price == 9200.0
    assert hotel.nightly_price == 4600.0
    assert hotel.availability == "available"
    assert len(hotel.rates) == 2
    assert hotel.rates[0].price_per_night == 4600.0
    assert hotel.rates[0].meal_plan is not None
    assert hotel.rates[0].meal_plan.startswith("Завтрак включён")
    assert hotel.rates[0].refundable is True
    assert hotel.rates[1].refundable is False
    assert hotel.rates[1].room_name == "Люкс с видом на море"


def test_hotel_details_excludes_nearby_hotels_and_date_carousel_prices():
    hotel = OzonTravelAdapter().parse_hotel_details(
        HOTEL_DETAILS_WITH_NEARBY_PRICES,
        url="https://www.ozon.ru/travel/hotels/product/garden-hills-1001/",
        destination="Сочи",
        check_in=date(2030, 10, 10),
        check_out=date(2030, 10, 12),
        context_verified=True,
    )

    assert hotel is not None
    assert hotel.total_price == 4142.0
    assert len(hotel.rates) == 1
    assert hotel.rates[0].room_name == "Эконом двухместный"


def test_hotel_details_requires_rendered_dates_guests_and_rooms():
    wrong_context = HOTEL_DETAILS_WITH_UI_NOISE.replace(
        "4 гостя", "2 гостя"
    ).replace(
        '- heading "Семейный номер" [level=2]',
        '- heading "Семейный номер" [level=2]\n- text: Вместимость до 4 гостей',
    ) + "\n- text: Другой тариф: нет мест"

    hotel, warnings = asyncio.run(
        OzonTravelAdapter().hotel_details(
            "https://www.ozon.ru/travel/hotels/product/park-otel-tri-umf-1781354057/",
            destination="Москва",
            check_in="2030-10-09",
            check_out="2030-10-11",
            adults=4,
            rooms=1,
            strategy="fixture",
            fixture_html=wrong_context,
        )
    )

    assert hotel is not None
    assert hotel.total_price is None
    assert hotel.nightly_price is None
    assert hotel.rates == []
    assert hotel.availability is None
    assert "GUEST_COUNT_UNVERIFIED" in warnings
    assert "PRICE_UNVERIFIED" in warnings
    assert hotel.raw["request_context"]["rendered_guest_counts"] == [2]


def test_hotel_details_marks_dates_and_room_count_unverified():
    unverified_context = HOTEL_DETAILS_WITH_UI_NOISE.replace(
        "9 окт. – 11 окт., 4 гостя, 1 номер",
        "8 окт. – 10 окт., 4 гостя",
    ).replace("Ваши даты 9 окт. – 11 окт.", "Ваши даты 8 окт. – 10 окт.")

    hotel, warnings = asyncio.run(
        OzonTravelAdapter().hotel_details(
            "https://www.ozon.ru/travel/hotels/product/park-otel-tri-umf-1781354057/",
            destination="Москва",
            check_in="2030-10-09",
            check_out="2030-10-11",
            adults=4,
            rooms=1,
            strategy="fixture",
            fixture_html=unverified_context,
        )
    )

    assert hotel is not None
    assert hotel.total_price is None
    assert hotel.rates == []
    assert "DATE_AVAILABILITY_UNVERIFIED" in warnings
    assert "ROOM_COUNT_UNVERIFIED" in warnings
    assert "PRICE_UNVERIFIED" in warnings


def test_single_named_rate_survives_unverified_single_booking_unit():
    single_unit_context = HOTEL_DETAILS_WITH_UI_NOISE.replace(
        ", 4 гостя, 1 номер", ", 4 гостя"
    )

    hotel, warnings = asyncio.run(
        OzonTravelAdapter().hotel_details(
            "https://www.ozon.ru/travel/hotels/product/park-otel-tri-umf-1781354057/",
            destination="Москва",
            check_in="2030-10-09",
            check_out="2030-10-11",
            adults=4,
            rooms=1,
            strategy="fixture",
            fixture_html=single_unit_context,
        )
    )

    assert hotel is not None
    assert hotel.total_price == 24000.0
    assert [rate.room_name for rate in hotel.rates] == ["Семейный номер"]
    assert "SINGLE_UNIT_RATE_QUOTE" in warnings
    assert "ROOM_COUNT_UNVERIFIED" not in warnings
    assert "PRICE_UNVERIFIED" not in warnings
    assert hotel.raw["request_context"]["single_unit_rate_context"] is True


def test_multiple_rooms_without_rendered_booking_count_fail_closed():
    missing_room_context = HOTEL_DETAILS_WITH_UI_NOISE.replace(
        ", 4 гостя, 1 номер", ", 4 гостя"
    )

    hotel, warnings = asyncio.run(
        OzonTravelAdapter().hotel_details(
            "https://www.ozon.ru/travel/hotels/product/park-otel-tri-umf-1781354057/",
            destination="Москва",
            check_in="2030-10-09",
            check_out="2030-10-11",
            adults=4,
            rooms=2,
            strategy="fixture",
            fixture_html=missing_room_context,
        )
    )

    assert hotel is not None
    assert hotel.total_price is None
    assert hotel.rates == []
    assert "ROOM_COUNT_UNVERIFIED" in warnings
    assert "PRICE_UNVERIFIED" in warnings


def test_hotel_rate_parser_ignores_auth_bonus_availability_and_carousel_prices():
    hotel = OzonTravelAdapter().parse_hotel_details(
        HOTEL_DETAILS_WITH_UI_NOISE,
        url="https://www.ozon.ru/travel/hotels/product/park-otel-tri-umf-1781354057/",
        destination="Москва",
        check_in=date(2030, 10, 9),
        check_out=date(2030, 10, 11),
        context_verified=True,
    )

    assert hotel is not None
    assert hotel.total_price == 24000.0
    assert [rate.room_name for rate in hotel.rates] == ["Семейный номер"]
    assert [rate.price for rate in hotel.rates] == [24000.0]


def test_live_rate_shape_keeps_named_unit_and_terms_without_footer_total():
    hotel, warnings = asyncio.run(
        OzonTravelAdapter().hotel_details(
            "https://www.ozon.ru/travel/hotels/product/park-otel-tri-umf-1781354057/",
            destination="Москва",
            check_in="2026-10-09",
            check_out="2026-10-11",
            adults=4,
            rooms=1,
            strategy="fixture",
            fixture_html=HOTEL_DETAILS_LIVE_RATES_SNAPSHOT,
        )
    )

    assert hotel is not None
    assert hotel.total_price == 52000.0
    assert hotel.nightly_price == 26000.0
    assert len(hotel.rates) == 2
    assert hotel.rates[0].room_name == (
        "Малый коттедж с двумя спальнями (1 двуспальная и 2 односпальные "
        "кровати) и сауной Черника, Ландыш, Клевер"
    )
    assert hotel.rates[1].room_name == (
        "Малый коттедж с двумя спальнями (1 двуспальная и 2 односпальные "
        "кровати) и сауной Брусника"
    )
    assert hotel.rates[0].meal_plan == "Завтрак"
    assert hotel.rates[0].cancellation_policy == "Бесплатная отмена до 8 окт."
    assert hotel.rates[0].payment_terms == "Оплата сейчас"
    assert "SINGLE_UNIT_RATE_QUOTE" in warnings
    assert "PRICE_UNVERIFIED" not in warnings
    assert hotel.raw["request_context"]["room_count_verified"] is False
    assert hotel.raw["request_context"]["rendered_room_counts"] == []
    assert hotel.distance_to_center == "Центр города 4.7 км"
    assert "5.9 км" not in hotel.raw["evidence"]


def test_almost_sold_out_is_not_reported_as_unavailable():
    hotel = OzonTravelAdapter().parse_hotel_details(
        '- heading "Отель Триумф, 4*" [level=1]\n- text: Почти распродано',
        url="https://www.ozon.ru/travel/hotels/product/park-otel-tri-umf-1781354057/",
        destination="Москва",
        check_in=date(2026, 10, 9),
        check_out=date(2026, 10, 11),
        context_verified=True,
    )

    assert hotel is not None
    assert hotel.total_price is None
    assert hotel.availability is None


def test_travel_request_validation_is_structured():
    async def run():
        adapter = OzonTravelAdapter()
        bad_flight = await adapter.search_flights(
            "MOW", "LED", "not-a-date", strategy="fixture"
        )
        bad_hotel = await adapter.search_hotels(
            "Сочи", "2030-05-12", "2030-05-10", strategy="fixture"
        )
        return bad_flight, bad_hotel

    bad_flight, bad_hotel = asyncio.run(run())
    assert bad_flight[1] == ["INVALID_DATE_FORMAT"]
    assert bad_hotel[1] == ["CHECK_OUT_NOT_AFTER_CHECK_IN"]


def test_hotel_details_rejects_non_ozon_url_without_loading(monkeypatch):
    async def fail_if_loaded(*_args, **_kwargs):
        raise AssertionError("non-Ozon URL must not be loaded")

    adapter = OzonTravelAdapter()
    monkeypatch.setattr(adapter, "_load_travel_page", fail_if_loaded)

    hotel, warnings = asyncio.run(
        adapter.hotel_details(
            "https://example.com/travel/hotels/product/fake/",
            destination="Сочи",
            check_in="2030-05-10",
            check_out="2030-05-12",
        )
    )

    assert hotel is None
    assert warnings == ["UNSUPPORTED_URL"]


def test_hotel_filter_does_not_treat_missing_dated_price_as_cheap():
    async def run():
        return await OzonTravelAdapter().search_hotels(
            "Сочи",
            "2030-05-10",
            "2030-05-12",
            max_total_price=10000,
            include_rates=False,
            strategy="fixture",
            fixture_html=HOTEL_RESULTS_HTML,
        )

    results, warnings, _ = asyncio.run(run())
    assert results == []
    assert "NO_RESULTS" in warnings
