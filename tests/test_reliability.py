import asyncio

import httpx
import pytest

from marketplaces_mcp.adapters import OzonAdapter, WildberriesAdapter, YandexMarketAdapter
from marketplaces_mcp.adapters.wildberries import _api_product_to_result
from marketplaces_mcp.core.matching import group_product_results
from marketplaces_mcp.core.models import ProductResult
from marketplaces_mcp.core.price_evidence import (
    is_public_price,
    price_metadata,
    price_sort_key,
)
from marketplaces_mcp.core.reviews import fetch_reviews, parse_reviews
from marketplaces_mcp.mcp_server import server
from marketplaces_mcp.mcp_server.server import _detect_marketplace, _safe_search


def test_wb_brand_is_not_seller_and_unknown_stock_is_not_available():
    p = _api_product_to_result({"id": 123, "name": "Game", "brand": "Nintendo", "salePriceU": 500000})
    assert p.seller is None
    assert p.availability is None
    assert p.raw["brand"] == "Nintendo"


def test_wb_timeout_falls_back_instead_of_crashing(monkeypatch):
    a = WildberriesAdapter()
    async def timeout(url):
        raise httpx.ReadTimeout("test")
    monkeypatch.setattr(a, "_request_wildberries_api", timeout)
    assert asyncio.run(a._search_with_public_api("test")) == ([], ["WILDBERRIES_API_FAILED"])


@pytest.mark.parametrize("adapter", [OzonAdapter, YandexMarketAdapter])
def test_recommendation_price_cannot_price_missing_primary_offer(adapter):
    p = adapter().parse_product_details('''- heading "Mario Kart World Nintendo Switch 2" [level=1]
- text: Товар закончился
- heading "Похожие товары" [level=2]
- text: 100 ₽
- button "В корзину"
''', "https://www.ozon.ru/product/example-123/" if adapter is OzonAdapter else "https://market.yandex.ru/card/example/123")
    assert p.price is None


def test_ozon_promo_link_does_not_steal_product_title():
    s = '''- link "Скидки недели":
  - /url: /product/mario-kart-world-123/
- text: 5 000 ₽ 7 000 ₽
- link "Mario Kart World Nintendo Switch 2":
  - /url: /product/mario-kart-world-123/
'''
    products = OzonAdapter().parse_search_results(s, "Mario Kart World")
    assert len(products) == 1
    assert products[0].title == "Mario Kart World Nintendo Switch 2"
    assert products[0].price == 5000


def test_ozon_product_title_number_is_not_price():
    s = '<article><a href="/product/mario-123/" title="Mario Kart World Nintendo Switch 2">Mario Kart World Nintendo Switch 2</a></article>'
    assert OzonAdapter().parse_search_results(s, "Mario")[0].price is None


def test_condition_is_explicit_and_not_a_public_price():
    assert price_metadata("5 000 ₽ С Ozon Картой", 5000)["price_kind"] == "conditional"
    assert price_metadata("Цена с картой Яндекс Пэй 5000 ₽", 5000)["price_kind"] == "conditional"
    assert price_metadata("от 5 000 ₽", 5000)["price_kind"] == "from"


def test_conditional_price_metadata_is_applied_to_all_rendered_search_paths():
    ozon = OzonAdapter().parse_search_results(
        '<article><a href="/product/x-123/" title="X">X</a>'
        '<span class="price">5 000 ₽ С Ozon Картой</span></article>',
        "x",
    )[0]
    yandex = YandexMarketAdapter().parse_search_results(
        '- link "X":\n  - /url: /card/x/123\n'
        '- text: Цена с картой Яндекс Пэй 5 000 ₽\n',
        "x",
    )[0]
    wildberries = WildberriesAdapter().parse_search_results(
        '<article class="product-card">'
        '<a href="/catalog/123/detail.aspx" aria-label="X"></a>'
        '<span>5 000 ₽ с WB Кошельком</span></article>',
        "x",
    )[0]

    assert [item.price_kind for item in (ozon, yandex, wildberries)] == [
        "conditional",
        "conditional",
        "conditional",
    ]
    assert all(item.price_condition for item in (ozon, yandex, wildberries))


def test_public_exact_price_sorts_first_and_non_public_is_not_eligible():
    exact = ProductResult(
        marketplace="ozon",
        title="Exact",
        url="https://www.ozon.ru/product/exact-1/",
        price=6000,
        price_kind="exact",
    )
    conditional = ProductResult(
        marketplace="ozon",
        title="Conditional",
        url="https://www.ozon.ru/product/conditional-2/",
        price=5000,
        price_kind="conditional",
        price_condition="Ozon card",
    )

    assert sorted([conditional, exact], key=price_sort_key) == [exact, conditional]
    assert is_public_price(exact)
    assert not is_public_price(conditional)


@pytest.mark.parametrize(
    ("adapter", "url"),
    [
        (OzonAdapter(), "https://www.ozon.ru/product/example-123/"),
        (YandexMarketAdapter(), "https://market.yandex.ru/card/example/123"),
        (WildberriesAdapter(), "https://www.wildberries.ru/catalog/123/detail.aspx"),
    ],
)
def test_html_recommendation_cannot_supply_primary_price_or_availability(adapter, url):
    product = adapter.parse_product_details(
        """<html><body><h1>Primary product</h1>
        <div>Товар закончился</div><h2>Похожие товары</h2>
        <div>100 ₽ <button>В корзину</button></div></body></html>""",
        url,
    )

    assert product is not None
    assert product.price is None
    assert product.availability is None


def test_ozon_second_current_amount_is_not_claimed_as_old_price():
    snapshot = """- text: 5 000 ₽ С Ozon Картой 5 500 ₽ без карты
- link "Product":
  - /url: /product/product-123/
"""

    product = OzonAdapter().parse_search_results(snapshot, "Product")[0]

    assert product.price == 5000
    assert product.price_kind == "conditional"
    assert product.old_price is None


def test_game_media_never_grouped_as_same_offer():
    def p(title):
        return ProductResult(marketplace="ozon", title=title, price=5000, url="https://www.ozon.ru/product/game-1/")
    products = [p("Mario Kart World Nintendo Switch 2 картридж"),
                p("Mario Kart World Nintendo Switch 2 цифровая версия"),
                p("Mario Kart World Nintendo Switch 2 game-key card")]
    assert len(group_product_results(products)) == 3


def test_no_reviews_is_successful_empty_read_without_retry(monkeypatch):
    from marketplaces_mcp.core.config import Settings
    a = YandexMarketAdapter(Settings(camofox_url="http://127.0.0.1:9377"))
    calls = []
    async def snapshot(url):
        calls.append(url)
        return '- main:\n  - heading "Нет отзывов и оценок" [level=2]'
    monkeypatch.setattr(a, "_fetch_with_camofox", snapshot)
    reviews, warnings, _, count, _ = asyncio.run(fetch_reviews(a, "https://market.yandex.ru/card/game/123", 2))
    assert reviews == [] and count == 0
    assert "REVIEWS_EMPTY" in warnings
    assert len(calls) == 1


def test_indented_review_snapshot_parses():
    snapshot = '''- main:
  - button "Покупатель" [e1]
  - text: 5 сентября 2026
  - button "Достоинства: Коробка и картридж целые. Комментарий: Работает." [e2]
'''
    reviews, _, _, _ = parse_reviews("yandex_market", snapshot, 2)
    assert len(reviews) == 1
    assert "картридж целые" in reviews[0].text


@pytest.mark.parametrize("url", ["https://evil.example/ozon.ru/product/1", "https://ozon.ru.evil.example/product/1", "http://127.0.0.1/?ozon.ru", "https://ozon.ru@evil.example/", "https://ozon.ru:9377/product/1"])
def test_marketplace_detection_requires_actual_https_host(url):
    assert _detect_marketplace(url) == "unknown"


def test_one_marketplace_exception_is_a_structured_failure():
    class Bad:
        marketplace = "wildberries"
        async def search(self, **kwargs):
            raise httpx.ConnectError("private transport details")
        def build_search_url(self, query):
            return "https://www.wildberries.ru/catalog/0/search.aspx"
    products, warnings, url = asyncio.run(_safe_search(Bad(), query="Mario", limit=2))
    assert products == []
    assert warnings == ["WILDBERRIES_SEARCH_FAILED_ConnectError"]
    assert "wildberries.ru" in url


def test_review_exception_is_a_structured_failure(monkeypatch):
    async def fail_reviews(*_args, **_kwargs):
        raise ValueError("private parser details")

    monkeypatch.setattr(server, "fetch_reviews", fail_reviews)
    response = asyncio.run(
        server.marketplaces_product_reviews(
            "https://www.ozon.ru/product/example-123/",
            limit=2,
        )
    )

    assert response.reviews == []
    assert response.warnings == ["REVIEWS_FAILED_ValueError"]
