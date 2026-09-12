from datetime import date

from marketplaces_mcp.adapters.package_tours import PackageToursAdapter


def test_package_tour_parser_keeps_full_total_party_and_all_inclusive():
    raw = {
        "price_all": "191&nbsp;877",
        "hotelNights": 10,
        "hotel_name": "Hotel Riu Dubai",
        "sd_s_full": "19.12.2026",
        "sd_e_full": "29.12.2026",
        "tour_place": "Дубай",
        "tour": "//www.1001tur.ru/tourdesc/oae/dubai/riu/abc/",
        "hotel_img": "//example.test/riu.jpg",
        "currency": "RUB",
        "hotel_cat": 4,
        "food_name": "всё включено",
        "room": "3ADL + 1INF standard",
        "adults": 3,
        "kids": 1,
        "infants": 1,
        "operator_name": "Fun & Sun",
        "departure_from": "Санкт-Петербург",
        "hotel_stop": "N",
        "dop_info_hotel": {
            "rate": "4.9",
            "reviews": 68,
            "beachLine": "1 линия",
            "dist_to_beach": "50",
            "beachTypeName": "Песчаный пляж",
        },
    }

    offer = PackageToursAdapter()._parse_offer(raw, origin_name="Санкт-Петербург")

    assert offer is not None
    assert offer.total_price == 191877.0
    assert offer.price_per_night == 19187.7
    assert offer.departure_date == date(2026, 12, 19)
    assert offer.return_date == date(2026, 12, 29)
    assert (offer.adults, offer.children, offer.infants) == (3, 0, 1)
    assert offer.meal_plan == "всё включено"
    assert offer.beach_distance_m == 50
    assert offer.provider == "1001tur"


def test_hotel_page_without_tour_permalink_is_not_a_package():
    raw = {
        "SupplierPriceRub": 150000,
        "Night": 5,
        "hotel_name": "Beach Hotel",
        "date": "2026-12-20",
        "tour_place_country": "ОАЭ",
        "fullUrl": "//hotels.1001tur.ru/oae/beach-hotel/",
        "adults": 3,
        "kids": 1,
        "infants": 1,
        "dop_info_hotel": {"dist_to_beach": ""},
    }

    offer = PackageToursAdapter()._parse_offer(raw, origin_name="Санкт-Петербург")

    assert offer is None
