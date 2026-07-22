from marketplaces_mcp.core.reviews import parse_reviews, reviews_url


OZON_REVIEWS = """
- heading "Отзывы о товаре 462 Наматрасник 60x120х15см белый" [level=1]
- text: Юлия Б. 18 июля 2026
- img
- img
- img
- img
- img
- text: Хороший, помогает спасать диван Вам помог этот отзыв?
- button "Да 0"
- text: Имя скрыто 7 мая 2026
- img
- img
- img
- img
- text: Размер впритык, край может завернуться Вам помог этот отзыв?
- text: 4.9 / 5 5 звёзд 434 4 звезды 20 3 звезды 6 2 звезды 1 1 звезда 1
"""

YANDEX_REVIEWS = """
- text: 4.9 524 оценки 91 отзыв
- button "Этот вариант" [e72]
- button "Елена" [e99]
- text: 26 февраля 2024
- 'button "Достоинства: Размер подошёл. Недостатки: нет. Комментарий: после стирки целый"':
- text: "Ширина: 60 см Цвет товара: белый Длина: 120 см"
- button "Иван" [e107]
- text: 19 декабря 2024
- 'button "Достоинства: мягкий. Недостатки: долго сохнет"':
"""


def test_review_urls_are_canonical():
    assert reviews_url(
        "ozon",
        "https://www.ozon.ru/product/example-123/?tracking=1",
    ) == "https://www.ozon.ru/product/example-123/reviews/"
    assert reviews_url(
        "yandex_market",
        "https://market.yandex.ru/card/example/123?offer=1",
    ) == "https://market.yandex.ru/card/example/123/reviews"


def test_ozon_review_snapshot_parsing():
    reviews, total, rating, warnings = parse_reviews("ozon", OZON_REVIEWS, limit=10)
    assert total == 462
    assert rating == 4.9
    assert len(reviews) == 2
    assert reviews[0].rating == 5.0
    assert reviews[1].rating == 4.0
    assert reviews[0].variant == "Наматрасник 60x120х15см белый"
    assert reviews[1].text == "Размер впритык, край может завернуться"
    assert warnings == ["REVIEW_SORT_PLATFORM_DEFAULT"]


def test_yandex_review_snapshot_marks_unconfirmed_variant_filter():
    reviews, total, rating, warnings = parse_reviews("yandex_market", YANDEX_REVIEWS, limit=10)
    assert total == 91
    assert rating == 4.9
    assert len(reviews) == 2
    assert reviews[0].author == "Елена"
    assert reviews[0].variant == "Ширина: 60 см Цвет товара: белый Длина: 120 см"
    assert reviews[1].variant is None
    assert "REVIEW_VARIANT_FILTER_NOT_CONFIRMED" in warnings
