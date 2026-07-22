from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from marketplaces_mcp.adapters import AvitoAdapter, OzonAdapter, WildberriesAdapter, YandexMarketAdapter
from marketplaces_mcp.core.config import Settings, get_settings
from marketplaces_mcp.core.reviews import fetch_reviews


OZON_FIXTURE_HTML = """
<html><body>
  <div class="tile-root">
    <a href="/product/abc" title="Книга офисная бумага А4 80 листов">Книга офисная бумага А4 80 листов</a>
    <span class="price">12 990 ₽</span>
    <div class="tile-hover-card__rating">4,7</div>
    <span class="tile-hover-card__reviews">125 отзывов</span>
    <img src="https://ozon.example/image.png" />
  </div>
</body></html>
"""

OZON_BLOCKED_HTML = """
<html><body>
  <div>Антибот-инцидент: доступ временно заблокирован. Пожалуйста, подтвердите, что вы не робот.</div>
</body></html>
"""

OZON_NO_JS_CHALLENGE_HTML = """
<html><head><title>Antibot Challenge Page</title></head><body>
  <h2>Пожалуйста, включите JavaScript для продолжения</h2>
  <span>Нам нужно убедиться, что вы не робот.</span>
  <h2>Please, enable JavaScript to continue</h2>
</body></html>
"""

OZON_MODERN_TILE_HTML = """
<html><body>
  <div class="tile-root">
    <a href="/product/svetocopy-a4-500-l-bumaga-dlya-printera-7969279/?at=token"><img src="https://ir.ozone.ru/a.jpg" /></a>
    <span>445 ₽</span><span>499 ₽</span><span>−10%</span>
    <a href="/product/svetocopy-a4-500-l-bumaga-dlya-printera-7969279/?at=token"><span>SvetoCopy A4 500 л Бумага для принтера</span></a>
    <span>4.8</span><span>696 830</span><span>Ozon</span>
  </div>
  <div class="tile-root">
    <a href="/product/ilim-standart-5-sht-a4-500-l-bumaga-dlya-printera-2973763863/?at=token"><span>Распродажа</span></a>
    <span>1 751 ₽</span><span>2 629 ₽</span><span>350 ₽ / шт</span>
    <a href="/product/ilim-standart-5-sht-a4-500-l-bumaga-dlya-printera-2973763863/?at=token"><span>ИЛИМ Стандарт 5 шт A4 500 л Бумага для принтера</span></a>
    <span>4.8</span><span>36 521</span><span>Ozon</span>
  </div>
</body></html>
"""

YANDEX_FIXTURE_HTML = """
<html><body>
  <script type="application/ld+json">
  {
    "@context": "https://schema.org",
    "@type": "ItemList",
    "itemListElement": [
      {
        "@type": "ListItem",
        "item": {
          "@type": "Product",
          "name": "Бумага для принтера A4 500 листов",
          "image": "https://market.yandex.ru/image.png",
          "offers": {
            "@type": "Offer",
            "price": "11900",
            "priceCurrency": "RUB",
            "url": "https://market.yandex.ru/product/def"
          },
          "aggregateRating": {
            "ratingValue": 4.5,
            "reviewCount": 44
          }
        }
      }
    ]
  }
  </script>
</body></html>
"""

YANDEX_RENDERED_FIXTURE_HTML = """
<html><body>
  <div data-zone-name="productSnippet">
    <a data-auto="snippet-link" href="/card/detskiy-namatrasnik-akvastop-60x120/102236642854?tracking=1">Наматрасник 120х60 непромокаемый</a>
    <div>Ширина: 60 см Длина: 120 см Цена с картой Яндекс Пэй 484 ₽ вместо 699 ₽ Пэй Рейтинг товара: 4.9 из 5 Оценок: (524) · 2.9K купили Послезавтра, ПВЗ В корзину</div>
  </div>
  <div data-zone-name="productSnippet">
    <a data-auto="snippet-link" href="/card/namatrasnik-peligrin-120x60/103836068979">Наматрасник Пелигрин 120х60</a>
    <div>Цена с картой Яндекс Пэй 370 ₽ вместо 410 ₽ Пэй Рейтинг товара: 4.8 из 5 Оценок: (15) · 80 купили Завтра, курьер В корзину</div>
  </div>
</body></html>
"""

YANDEX_MODERN_SEARCH_HTML = """
<html><body>
  <div data-zone-name="productSnippet">
    <div data-zone-name="title">
      <a href="/card/mekhanicheskiye-pereklyuchateli-kailh-box-navy-klikayushchiye-110-shtuk/5694381852?do-waremd5=token">
        Механические переключатели Kailh Box Navy (кликающие) 110 штук
      </a>
    </div>
    <div>Цвет товара: темно-синий, темно-синий</div>
    <a href="/card/mekhanicheskiye-pereklyuchateli-kailh-box-navy-klikayushchiye-110-shtuk/5694381852?do-waremd5=token">
      Цена с картой Яндекс Пэй 5 833 ₽ вместо 5 833 ₽ Пэй
    </a>
    <div>Рейтинг товара: 4.8 из 5 Оценок: (12) · 42 купили До 7 дней, ПВЗ В корзину</div>
  </div>
  <div data-zone-name="productSnippet">
    <div data-zone-name="title">
      <a href="/card/mekhanicheskiye-pereklyuchateli-kailh-box-navy-klikayushchiye-90-shtuk/5693904311?do-waremd5=token">
        Механические переключатели Kailh Box Navy (кликающие) 90 штук
      </a>
    </div>
    <a href="/card/mekhanicheskiye-pereklyuchateli-kailh-box-navy-klikayushchiye-90-shtuk/5693904311?do-waremd5=token">
      Цена с картой Яндекс Пэй 4 859 ₽ вместо 4 859 ₽ Пэй
    </a>
  </div>
</body></html>
"""

WILDBERRIES_FIXTURE_HTML = """
<html><body>
  <article class="product-card">
    <a href="/catalog/5148062/detail.aspx?targetUrl=GP" aria-label="Наматрасник детский 60x120 TPU"></a>
    <span class="price">799 ₽</span><button>В корзину</button>
  </article>
</body></html>
"""

OZON_CAMOFOX_SNAPSHOT = """
- link "Распродажа":
  - /url: /product/namatrasnik-60x120h15sm-belyy-750317510/?tracking=1
- text: 374 ₽ 999 ₽ −62% 344 шт осталось
- link "Наматрасник 60x120х15см белый":
  - /url: /product/namatrasnik-60x120h15sm-belyy-750317510/?tracking=1
- text: "5.0"
- text: 462 отзыва
- button "Завтра":
  - text: Завтра
"""

YANDEX_CAMOFOX_SNAPSHOT = """
- article:
  - link "Наматрасник 120х60 непромокаемый 10 % ПРОМОКОД":
    - /url: /card/detskiy-nepromokayemyy-namatrasnik-akvastop-60x120/102236642854?tracking=1
  - link "Наматрасник 120х60 непромокаемый":
    - /url: /card/detskiy-nepromokayemyy-namatrasnik-akvastop-60x120/102236642854?tracking=1
  - text: "Цвет товара: белый Ширина: 60 см Длина: 120 см"
  - link "Цена с картой Яндекс Пэй 484 ₽ вместо 699 ₽ Пэй":
    - /url: /card/detskiy-nepromokayemyy-namatrasnik-akvastop-60x120/102236642854?tracking=1
  - text: Рейтинг товара: 4.9 из 5 Оценок: (524) · 2.9K купили
  - text: Послезавтра, ПВЗ
  - button "В корзину"
"""

OZON_CAMOFOX_DETAIL_SNAPSHOT = """
- heading "Наматрасник 60x120х15см белый" [level=1]
- button "374 ₽ С банками":
  - text: 374 ₽ С банками
- text: 416 ₽ 999 ₽ С другими банками
- button "В корзину"
- heading "Описание" [level=2]
- text: Детский наматрасник изготовлен из махрового трикотажа с мембранным покрытием TPU.
- heading "Характеристики" [level=2]
- term: Название материала
- definition: Махра, мембрана TPU
"""

YANDEX_CAMOFOX_DETAIL_SNAPSHOT = """
- heading "Наматрасник 120х60 непромокаемый" [level=1]
- button "484 ₽ Пэй 4 646 ₽ –90%":
  - button "484 ₽"
- text: Доставка Маркета Послезавтра
- button "В корзину"
- heading "О товаре" [level=2]
- text: Тканевые слои изготовлены из мягкой махры и водонепроницаемой дышащей мембраны.
- heading "Характеристики" [level=2]
- term: Размер
- definition: 60 x 120 см
"""

AVITO_CAMOFOX_DETAIL_SNAPSHOT = """
- heading "Кроватка stokke sleepi" [level=1]
- button
- text: Кроватка stokke sleepi 15 000 ₽ Пользователь
- button "Купить"
- heading "О кровати" [level=2]
- list:
  - listitem:
    - paragraph: "Состояние: Хорошее"
  - listitem:
    - paragraph: "Внешний вид: Потёртости, царапины"
- heading "Характеристики" [level=2]
- list:
  - listitem:
    - paragraph: "Каркас: Дерево"
- heading "Описание" [level=2]
- paragraph: "Кроватка-трансформер Stokke из бука."
- paragraph: "В комплекте два дна, колёса и два матраса."
- button "Читать полностью"
- heading "Местоположение" [level=2]
- paragraph
- paragraph: Пушкин
- article:
  - paragraph: № 8217100311 · 18 июля в 13:28 · 173 просмотра (+2 сегодня)
- button "Купить с доставкой"
- paragraph: Авито Доставка.
- heading "Пользователь" [level=3]
- text: 4,8
- link "76 отзывов":
  - /url: "#open-reviews-list"
- paragraph: Частное лицо
"""


def test_ozon_fixture_parsing():
    async def run():
        adapter = OzonAdapter()
        results, warnings, _ = await adapter.search(
            query="бумага",
            limit=3,
            strategy="fixture",
            fixture_html=OZON_FIXTURE_HTML,
        )
        return results, warnings

    results, warnings = asyncio.run(run())
    assert not warnings
    assert len(results) == 1
    product = results[0]
    assert product.marketplace == "ozon"
    assert product.title == "Книга офисная бумага А4 80 листов"
    assert product.price == 12990
    assert product.old_price is None
    assert product.rating == 4.7
    assert product.reviews_count == 125
    assert product.url.endswith("/product/abc")


def test_ozon_fixture_blocked_returns_captcha_warning():
    async def run():
        adapter = OzonAdapter()
        results, warnings, _ = await adapter.search(
            query="бумага",
            limit=3,
            strategy="fixture",
            fixture_html=OZON_BLOCKED_HTML,
        )
        return results, warnings

    results, warnings = asyncio.run(run())
    assert warnings == ["CAPTCHA_OR_BLOCKED"]
    assert len(results) == 0


def test_ozon_no_javascript_challenge_returns_captcha_warning():
    async def run():
        adapter = OzonAdapter()
        results, warnings, _ = await adapter.search(
            query="бумага",
            limit=3,
            strategy="fixture",
            fixture_html=OZON_NO_JS_CHALLENGE_HTML,
        )
        return results, warnings

    results, warnings = asyncio.run(run())
    assert warnings == ["CAPTCHA_OR_BLOCKED"]
    assert len(results) == 0


def test_ozon_modern_tile_parsing_prefers_product_title_over_badges():
    async def run():
        adapter = OzonAdapter()
        results, warnings, _ = await adapter.search(
            query="бумага",
            limit=3,
            strategy="fixture",
            fixture_html=OZON_MODERN_TILE_HTML,
        )
        return results, warnings

    results, warnings = asyncio.run(run())

    assert not warnings
    assert len(results) == 2
    assert results[0].title == "SvetoCopy A4 500 л Бумага для принтера"
    assert results[0].url == "https://www.ozon.ru/product/svetocopy-a4-500-l-bumaga-dlya-printera-7969279/"
    assert results[0].price == 445
    assert results[1].title == "ИЛИМ Стандарт 5 шт A4 500 л Бумага для принтера"
    assert results[1].title != "Распродажа"
    assert results[1].price == 1751


def test_ozon_playwright_uses_headful_when_proxy_configured():
    adapter = OzonAdapter(Settings(proxies={"ozon": "http://127.0.0.1:8080", "yandex_market": ""}, browser_headless=True))
    assert adapter._playwright_headless() is False


def test_ozon_playwright_uses_global_headless_without_proxy():
    adapter = OzonAdapter(Settings(proxies={"ozon": "", "yandex_market": ""}, browser_headless=True))
    assert adapter._playwright_headless() is True


def test_playwright_options_include_browser_config():
    adapter = OzonAdapter(
        Settings(
            proxies={"ozon": "http://127.0.0.1:8080"},
            browser_headless=True,
            browser_channel="chrome",
            browser_args=["--disable-blink-features=AutomationControlled"],
            browser_locale="ru-RU",
            browser_timezone="Europe/Moscow",
            browser_default_user_agent=True,
        )
    )

    assert adapter._playwright_launch_options() == {
        "headless": False,
        "proxy": {"server": "http://127.0.0.1:8080"},
        "channel": "chrome",
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    assert adapter._playwright_context_options() == {
        "java_script_enabled": True,
        "locale": "ru-RU",
        "timezone_id": "Europe/Moscow",
    }
    assert adapter._playwright_settle_timeout_ms() == 3000


def test_yandex_fixture_parsing():
    async def run():
        adapter = YandexMarketAdapter()
        results, warnings, _ = await adapter.search(
            query="бумага",
            limit=3,
            strategy="fixture",
            fixture_html=YANDEX_FIXTURE_HTML,
        )
        return results, warnings

    results, warnings = asyncio.run(run())
    assert not warnings
    assert len(results) == 1
    product = results[0]
    assert product.marketplace == "yandex_market"
    assert product.title == "Бумага для принтера A4 500 листов"
    assert product.price == 11900
    assert product.rating == 4.5
    assert product.reviews_count == 44


def test_yandex_rendered_dom_fixture_parsing_is_product_agnostic():
    async def run():
        adapter = YandexMarketAdapter()
        results, warnings, _ = await adapter.search(
            query="детский наматрасник 60x120",
            limit=3,
            strategy="fixture",
            fixture_html=YANDEX_RENDERED_FIXTURE_HTML,
        )
        return results, warnings

    results, warnings = asyncio.run(run())
    assert not warnings
    assert len(results) == 2
    first = results[0]
    assert first.marketplace == "yandex_market"
    assert first.price == 484.0
    assert first.old_price == 699.0
    assert first.rating == 4.9
    assert first.reviews_count == 524
    assert first.url == "https://market.yandex.ru/card/detskiy-namatrasnik-akvastop-60x120/102236642854"
    assert first.delivery_hint == "Послезавтра, ПВЗ"


def test_yandex_modern_search_card_parsing_uses_title_zone_link():
    async def run():
        adapter = YandexMarketAdapter()
        results, warnings, _ = await adapter.search(
            query="Kailh Box Navy 100",
            limit=3,
            strategy="fixture",
            fixture_html=YANDEX_MODERN_SEARCH_HTML,
        )
        return results, warnings

    results, warnings = asyncio.run(run())
    assert not warnings
    assert len(results) == 2
    first = results[0]
    assert first.marketplace == "yandex_market"
    assert first.title == "Механические переключатели Kailh Box Navy (кликающие) 110 штук"
    assert first.url == "https://market.yandex.ru/card/mekhanicheskiye-pereklyuchateli-kailh-box-navy-klikayushchiye-110-shtuk/5694381852"
    assert first.price == 5833.0
    assert first.rating == 4.8
    assert first.reviews_count == 12
    assert first.delivery_hint == "До 7 дней, ПВЗ"


def test_wildberries_fixture_parsing():
    async def run():
        return await WildberriesAdapter().search(
            query="детский наматрасник",
            limit=2,
            strategy="fixture",
            fixture_html=WILDBERRIES_FIXTURE_HTML,
        )

    results, warnings, _ = asyncio.run(run())
    assert not warnings
    assert len(results) == 1
    assert results[0].title == "Наматрасник детский 60x120 TPU"
    assert results[0].price == 799.0
    assert results[0].url == "https://www.wildberries.ru/catalog/5148062/detail.aspx"


def test_ozon_camofox_snapshot_parsing():
    results = OzonAdapter().parse_search_results(OZON_CAMOFOX_SNAPSHOT, query="наматрасник")
    assert len(results) == 1
    assert results[0].price == 374.0
    assert results[0].old_price == 999.0
    assert results[0].rating == 5.0
    assert results[0].reviews_count == 462
    assert results[0].availability == "344 шт осталось"
    assert results[0].delivery_hint == "Завтра"


def test_yandex_camofox_snapshot_parsing():
    results = YandexMarketAdapter().parse_search_results(YANDEX_CAMOFOX_SNAPSHOT, query="наматрасник")
    assert len(results) == 1
    assert results[0].title == "Наматрасник 120х60 непромокаемый"
    assert results[0].price == 484.0
    assert results[0].old_price == 699.0
    assert results[0].rating == 4.9
    assert results[0].reviews_count == 524
    assert results[0].availability == "available"


def test_ozon_camofox_product_details_keep_material_evidence():
    product = OzonAdapter().parse_product_details(
        OZON_CAMOFOX_DETAIL_SNAPSHOT,
        url="https://www.ozon.ru/product/namatrasnik-60x120h15sm-belyy-750317510/?tracking=1",
    )
    assert product is not None
    assert product.price == 374.0
    assert product.url == "https://www.ozon.ru/product/namatrasnik-60x120h15sm-belyy-750317510/"
    assert product.raw is not None
    assert "мембранным покрытием TPU" in product.raw["evidence_excerpt"]


def test_yandex_camofox_product_details_keep_material_evidence():
    product = YandexMarketAdapter().parse_product_details(
        YANDEX_CAMOFOX_DETAIL_SNAPSHOT,
        url="https://market.yandex.ru/card/detskiy-namatrasnik/102236642854?tracking=1",
    )
    assert product is not None
    assert product.price == 484.0
    assert product.url == "https://market.yandex.ru/card/detskiy-namatrasnik/102236642854"
    assert product.raw is not None
    assert "водонепроницаемой дышащей мембраны" in product.raw["evidence_excerpt"]


def test_camofox_warning_reports_not_configured_for_search_details_and_reviews():
    async def run():
        adapter = OzonAdapter(Settings(camofox_url=""))
        search_results, search_warnings = await adapter._search_with_camofox(
            "https://www.ozon.ru/search/?text=namatrasnik",
            "namatrasnik",
        )
        product, details_warnings = await adapter._details_with_camofox(
            "https://www.ozon.ru/product/namatrasnik-1/"
        )
        reviews, review_warnings, _, _, _ = await fetch_reviews(
            adapter,
            "https://www.ozon.ru/product/namatrasnik-1/",
            limit=3,
        )
        return search_results, search_warnings, product, details_warnings, reviews, review_warnings

    search_results, search_warnings, product, details_warnings, reviews, review_warnings = asyncio.run(run())
    assert search_results == []
    assert search_warnings == ["CAMOFOX_NOT_CONFIGURED"]
    assert product is None
    assert details_warnings == ["CAMOFOX_NOT_CONFIGURED"]
    assert reviews == []
    assert review_warnings == ["CAMOFOX_NOT_CONFIGURED"]


def test_camofox_warning_reports_runtime_failure_when_configured(monkeypatch):
    async def run():
        adapter = OzonAdapter(Settings(camofox_url="http://127.0.0.1:9"))

        async def failing_camofox(_url: str):
            raise RuntimeError("runtime unavailable")

        monkeypatch.setattr(adapter, "_fetch_with_camofox", failing_camofox)
        search_results, search_warnings = await adapter._search_with_camofox(
            "https://www.ozon.ru/search/?text=namatrasnik",
            "namatrasnik",
        )
        product, details_warnings = await adapter._details_with_camofox(
            "https://www.ozon.ru/product/namatrasnik-1/"
        )
        reviews, review_warnings, _, _, _ = await fetch_reviews(
            adapter,
            "https://www.ozon.ru/product/namatrasnik-1/",
            limit=3,
        )
        return search_results, search_warnings, product, details_warnings, reviews, review_warnings

    search_results, search_warnings, product, details_warnings, reviews, review_warnings = asyncio.run(run())
    assert search_results == []
    assert search_warnings == ["CAMOFOX_FAILED"]
    assert product is None
    assert details_warnings == ["CAMOFOX_FAILED", "CAMOFOX_RETRIED"]
    assert reviews == []
    assert review_warnings == ["CAMOFOX_FAILED", "CAMOFOX_RETRIED"]


def test_avito_camofox_product_details_keep_used_offer_evidence():
    product = AvitoAdapter().parse_product_details(
        AVITO_CAMOFOX_DETAIL_SNAPSHOT,
        url=(
            "https://www.avito.ru/sankt-peterburg_pushkin/tovary_dlya_detey_i_igrushki/"
            "krovatka_stokke_sleepi_8217100311?context=1"
        ),
    )
    assert product is not None
    assert product.marketplace == "avito"
    assert product.price == 15000.0
    assert product.condition == "Хорошее"
    assert product.location == "Пушкин"
    assert product.seller == "Пользователь"
    assert product.seller_type == "Частное лицо"
    assert product.seller_rating == 4.8
    assert product.seller_reviews_count == 76
    assert product.views_count == 173
    assert product.delivery_available is True
    assert product.availability == "available"
    assert product.url.endswith("_8217100311")
    assert product.raw is not None
    assert product.raw["listing_id"] == "8217100311"
    assert product.raw["appearance"] == "Потёртости, царапины"
    assert "два матраса" in product.raw["description"]


def test_avito_removed_listing_does_not_take_similar_offer_price():
    snapshot = """
- heading "Кроватка Stokke Sleepi" [level=1]
- strong: Объявление снято с публикации.
- heading "Похожие объявления" [level=3]
- text: 7 000 ₽
"""
    product = AvitoAdapter().parse_product_details(
        snapshot,
        url="https://www.avito.ru/moskva/detskaya_mebel/krovatka_stokke_7300366172",
    )
    assert product is not None
    assert product.availability == "removed"
    assert product.price is None


def test_avito_exact_listing_url_filter_rejects_search_pages():
    adapter = AvitoAdapter()
    assert adapter.is_product_url(
        "https://www.avito.ru/moskva/tovary_dlya_detey/krovatka_stokke_8217100311"
    )
    assert not adapter.is_product_url(
        "https://www.avito.ru/all/tovary_dlya_detey?q=stokke"
    )


def test_avito_ip_limit_is_classified_as_blocked():
    snapshot = """
- 'heading "Доступ ограничен: проблема с IP" [level=2]'
- paragraph: Нажмите Продолжить для решения капчи
"""
    assert AvitoAdapter()._is_blocked(snapshot)


def test_avito_search_uses_configured_region():
    settings = Settings(avito_region_slug="sankt-peterburg")
    url = AvitoAdapter(settings).build_search_url("кроватка Stokke")
    assert url.startswith("https://www.avito.ru/sankt-peterburg?q=")
    assert "%D0%BA%D1%80%D0%BE%D0%B2%D0%B0%D1%82%D0%BA%D0%B0" in url


def test_avito_search_uses_anonymous_readonly_camofox(tmp_path, monkeypatch):
    async def run():
        settings = Settings(
            avito_region_slug="sankt-peterburg",
            avito_state_path=tmp_path / "avito-state.json",
            avito_min_interval_seconds=0,
        )
        adapter = AvitoAdapter(settings)

        async def camofox_snapshot(_url: str):
            return """
- link "Кроватка Stokke Sleepi":
  - /url: /sankt-peterburg/tovary_dlya_detey/krovatka_stokke_sleepi_8217100311
"""

        monkeypatch.setattr(adapter, "_fetch_with_camofox", camofox_snapshot)
        return await adapter.search("кроватка Stokke", limit=3)

    results, warnings, search_url = asyncio.run(run())
    assert len(results) == 1
    assert results[0].url.endswith("_8217100311")
    assert warnings == ["CAMOFOX_READONLY"]
    assert "/sankt-peterburg?" in search_url


def test_avito_ip_block_starts_shared_cooldown(tmp_path, monkeypatch):
    async def run():
        settings = Settings(
            avito_state_path=tmp_path / "avito-state.json",
            avito_min_interval_seconds=0,
            avito_block_cooldown_seconds=600,
        )
        first = AvitoAdapter(settings)
        calls = {"count": 0}

        async def blocked_snapshot(_url: str):
            calls["count"] += 1
            return '- heading "Доступ ограничен: проблема с IP" [level=2]'

        async def no_index(_query: str, _limit: int):
            return [], ["INDEX_DISCOVERY_NO_RESULTS"]

        monkeypatch.setattr(first, "_fetch_with_camofox", blocked_snapshot)
        monkeypatch.setattr(first, "_discover_indexed", no_index)
        _, first_warnings, _ = await first.search("кроватка", limit=1)

        second = AvitoAdapter(settings)

        async def forbidden_snapshot(_url: str):
            raise AssertionError("shared cooldown must skip the second live request")

        monkeypatch.setattr(second, "_fetch_with_camofox", forbidden_snapshot)
        _, second_warnings, _ = await second.product_details(
            "https://www.avito.ru/sankt-peterburg/detskaya_mebel/krovatka_8217100311"
        )
        return calls, first_warnings, second_warnings, settings.avito_state_path

    calls, first_warnings, second_warnings, state_path = asyncio.run(run())
    assert calls["count"] == 1
    assert "AVITO_IP_BLOCKED" in first_warnings
    assert second_warnings == ["AVITO_IP_COOLDOWN"]
    assert os.stat(state_path).st_mode & 0o777 == 0o600


def test_avito_state_path_can_live_under_existing_shared_directory(monkeypatch):
    state_path = Path(os.path.abspath(os.path.join(os.sep, "tmp", "marketplaces-avito-state-test.json")))

    async def run():
        settings = Settings(
            avito_state_path=state_path,
            avito_min_interval_seconds=0,
        )
        adapter = AvitoAdapter(settings)

        async def no_snapshot(_url: str):
            return None

        async def no_index(_query: str, _limit: int):
            return [], ["INDEX_DISCOVERY_NO_RESULTS"]

        monkeypatch.setattr(adapter, "_fetch_with_camofox", no_snapshot)
        monkeypatch.setattr(adapter, "_discover_indexed", no_index)
        return await adapter.search("кроватка", limit=1)

    try:
        results, warnings, _ = asyncio.run(run())
        assert results == []
        assert "AVITO_LIVE_NO_RESULTS" in warnings
        assert os.stat(state_path).st_mode & 0o777 == 0o600
    finally:
        for path in (state_path, Path(f"{state_path}.lock")):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass


def test_fixture_strategy_never_uses_live_or_index_fallback(monkeypatch):
    async def run():
        adapter = OzonAdapter()

        async def forbidden_camofox(_url: str):
            raise AssertionError("fixture mode must not call Camofox")

        async def forbidden_index(_query: str, _limit: int):
            raise AssertionError("fixture mode must not call public search index")

        monkeypatch.setattr(adapter, "_fetch_with_camofox", forbidden_camofox)
        monkeypatch.setattr(adapter, "_discover_indexed", forbidden_index)
        missing = await adapter.search("missing fixture", limit=1, strategy="fixture")
        empty = await adapter.search("empty fixture", limit=1, strategy="fixture", fixture_html="<html></html>")
        details = await adapter.product_details(
            "https://www.ozon.ru/product/missing-1/",
            strategy="fixture",
            fixture_html="<html></html>",
        )
        return missing, empty, details

    (missing_results, missing_warnings, _), (empty_results, empty_warnings, _), (product, details_warnings, _) = asyncio.run(run())
    assert missing_results == []
    assert missing_warnings == ["FIXTURE_NOT_FOUND"]
    assert empty_results == []
    assert empty_warnings == ["NO_RESULTS"]
    assert product is None
    assert details_warnings == ["NO_RESULTS"]


def test_blocked_hive_recovers_with_camofox(monkeypatch):
    async def run():
        async def blocked_hive(self, _url: str):
            return "<html><title>Antibot Captcha</title><body>Confirm that you're not a bot</body></html>"

        async def camofox_snapshot(self, _url: str):
            return YANDEX_CAMOFOX_SNAPSHOT

        monkeypatch.setattr(YandexMarketAdapter, "_fetch_with_hive_web", blocked_hive)
        monkeypatch.setattr(YandexMarketAdapter, "_fetch_with_camofox", camofox_snapshot)
        return await YandexMarketAdapter().search(query="наматрасник", limit=2)

    results, warnings, _ = asyncio.run(run())
    assert len(results) == 1
    assert "HIVE_WEB_BLOCKED" in warnings
    assert "CAMOFOX_FALLBACK" in warnings
    assert "CAPTCHA_OR_BLOCKED" not in warnings


def test_yandex_blocked_hive_falls_back_to_direct_search_html(monkeypatch):
    async def run():
        calls = {"http": 0}

        async def blocked_hive(self, _url: str):
            return "<html><title>Antibot Captcha</title><body>Confirm that you're not a bot</body></html>"

        async def no_camofox(self, _url: str):
            return None

        async def no_index_results(self, _query: str, _limit: int):
            return [], ["INDEX_DISCOVERY_NO_RESULTS"]

        async def direct_search_html(self, url: str):
            calls["http"] += 1
            assert "local-offers-first=0" in url
            return YANDEX_MODERN_SEARCH_HTML

        monkeypatch.setattr(YandexMarketAdapter, "_fetch_with_hive_web", blocked_hive)
        monkeypatch.setattr(YandexMarketAdapter, "_fetch_with_camofox", no_camofox)
        monkeypatch.setattr(YandexMarketAdapter, "_discover_indexed", no_index_results)
        monkeypatch.setattr(YandexMarketAdapter, "_fetch_with_http", direct_search_html)

        adapter = YandexMarketAdapter(Settings(web_backend="hive_web"))
        results, warnings, _ = await adapter.search(query="Kailh Box Navy 100", limit=3, strategy="auto")
        return results, warnings, calls

    results, warnings, calls = asyncio.run(run())
    assert len(results) == 2
    assert results[0].title == "Механические переключатели Kailh Box Navy (кликающие) 110 штук"
    assert "HIVE_WEB_BLOCKED" in warnings
    assert "YANDEX_HTTP_FALLBACK" in warnings
    assert calls["http"] == 1


def test_product_details_retries_one_empty_camofox_snapshot(monkeypatch):
    async def run():
        snapshots = iter(["- main: loading", OZON_CAMOFOX_DETAIL_SNAPSHOT])

        async def blocked_hive(self, _url: str):
            return "<html><title>Antibot Captcha</title></html>"

        async def next_snapshot(self, _url: str):
            return next(snapshots)

        monkeypatch.setattr(OzonAdapter, "_fetch_with_hive_web", blocked_hive)
        monkeypatch.setattr(OzonAdapter, "_fetch_with_camofox", next_snapshot)
        return await OzonAdapter().product_details(
            "https://www.ozon.ru/product/namatrasnik-60x120h15sm-belyy-750317510/"
        )

    product, warnings, _ = asyncio.run(run())
    assert product is not None
    assert product.price == 374.0
    assert "CAMOFOX_RETRIED" in warnings



def test_yandex_default_backend_uses_hive_web_rendered_dom(monkeypatch):
    async def run():
        calls = {"hive": 0}

        async def fake_hive_web(self, _url: str):
            calls["hive"] += 1
            return YANDEX_RENDERED_FIXTURE_HTML

        monkeypatch.setenv("MARKETPLACES_WEB_BACKEND", "hive_web")
        monkeypatch.setattr(YandexMarketAdapter, "_fetch_with_hive_web", fake_hive_web)
        adapter = YandexMarketAdapter()
        results, warnings, _ = await adapter.search(query="детский наматрасник", limit=3, strategy="auto")
        return results, warnings, calls["hive"]

    results, warnings, calls = asyncio.run(run())
    assert not warnings
    assert calls == 1
    assert len(results) == 2


def test_yandex_hive_web_failure_does_not_use_legacy_loader(monkeypatch):
    async def run():
        calls = {"hive": 0, "playwright": 0, "http": 0}

        async def failing_hive_web(self, _url: str):
            calls["hive"] += 1
            raise RuntimeError("hive web failed")

        async def legacy_called(self, _url: str):
            calls["playwright"] += 1
            return "<html><body>legacy</body></html>"

        async def legacy_http(self, _url: str):
            calls["http"] += 1
            return "<html><body>legacy-http</body></html>"

        async def no_index_results(self, _query: str, _limit: int):
            return [], ["INDEX_DISCOVERY_NO_RESULTS"]

        async def no_camofox(self, _url: str):
            return None

        monkeypatch.setenv("MARKETPLACES_WEB_BACKEND", "hive_web")
        monkeypatch.setattr(YandexMarketAdapter, "_fetch_with_hive_web", failing_hive_web)
        monkeypatch.setattr(YandexMarketAdapter, "_fetch_with_playwright", legacy_called)
        monkeypatch.setattr(YandexMarketAdapter, "_fetch_with_http", legacy_http)
        monkeypatch.setattr(YandexMarketAdapter, "_fetch_with_camofox", no_camofox)
        monkeypatch.setattr(YandexMarketAdapter, "_discover_indexed", no_index_results)

        results, warnings, _ = await YandexMarketAdapter().search(
            query="детский наматрасник",
            limit=3,
            strategy="auto",
        )
        return results, warnings, calls

    results, warnings, calls = asyncio.run(run())
    assert not results
    assert "HIVE_WEB_FAILED" in warnings
    assert calls["hive"] == 1
    assert calls["playwright"] == 0
    assert calls["http"] == 0


def test_fixture_strategy_bypasses_hive_web(monkeypatch):
    async def run():
        async def fail_hive(self, _url: str):
            raise AssertionError("hive web should not run")

        calls = {"hive": 0}

        async def counting_hive(self, _url: str):
            calls["hive"] += 1
            return await fail_hive(self, _url)

        monkeypatch.setenv("MARKETPLACES_WEB_BACKEND", "hive_web")
        monkeypatch.setattr(YandexMarketAdapter, "_fetch_with_hive_web", counting_hive)
        results, warnings, _ = await YandexMarketAdapter().search(
            query="детский наматрасник",
            limit=3,
            strategy="fixture",
            fixture_html=YANDEX_RENDERED_FIXTURE_HTML,
        )
        return results, warnings, calls["hive"]

    results, warnings, calls = asyncio.run(run())
    assert not warnings
    assert calls == 0
    assert len(results) == 2


def test_config_file_loads_per_marketplace_proxies(tmp_path, monkeypatch):
    config_path = tmp_path / "marketplaces.json"
    config_path.write_text(
        json.dumps(
            {
                "web_backend": "auto",
                "hive_web_max_tokens": 4321,
                "browser_headless": False,
                "browser_channel": "chrome",
                "browser_args": ["--disable-blink-features=AutomationControlled"],
                "browser_locale": "ru-RU",
                "browser_timezone": "Europe/Moscow",
                "browser_default_user_agent": True,
                "proxies": {
                    "ozon": "socks5h://user:pass@example.test:19080",
                    "yandex_market": None,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MARKETPLACES_CONFIG", str(config_path))

    settings = get_settings()

    assert settings.config_path == config_path
    assert settings.web_backend == "auto"
    assert settings.hive_web_max_tokens == 4321
    assert settings.browser_headless is False
    assert settings.browser_channel == "chrome"
    assert settings.browser_args == ["--disable-blink-features=AutomationControlled"]
    assert settings.browser_locale == "ru-RU"
    assert settings.browser_timezone == "Europe/Moscow"
    assert settings.browser_default_user_agent is True
    assert settings.proxy_url_for("ozon") == "socks5h://user:pass@example.test:19080"
    assert settings.proxy_url_for("yandex_market") is None


def test_proxy_env_overrides_config_file(tmp_path, monkeypatch):
    config_path = tmp_path / "marketplaces.json"
    config_path.write_text(
        json.dumps({"proxies": {"ozon": "socks5://config.example:1080"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("MARKETPLACES_CONFIG", str(config_path))
    monkeypatch.setenv("MARKETPLACES_PROXY_OZON_URL", "socks5h://env.example:19080")

    assert get_settings().proxy_url_for("ozon") == "socks5h://env.example:19080"


def test_ozon_proxy_skips_hive_web_even_when_backend_is_hive_web(monkeypatch):
    async def run():
        calls = {"hive": 0, "playwright": 0, "http": 0}

        async def failing_hive_web(self, _url: str):
            calls["hive"] += 1
            raise AssertionError("hive web should not run when marketplace proxy is configured")

        async def proxied_playwright(self, _url: str):
            calls["playwright"] += 1
            return OZON_FIXTURE_HTML

        async def fallback_http(self, _url: str):
            calls["http"] += 1
            return None

        monkeypatch.setattr(OzonAdapter, "_fetch_with_hive_web", failing_hive_web)
        monkeypatch.setattr(OzonAdapter, "_fetch_with_playwright", proxied_playwright)
        monkeypatch.setattr(OzonAdapter, "_fetch_with_http", fallback_http)

        adapter = OzonAdapter(
            Settings(web_backend="hive_web", proxies={"ozon": "socks5h://user:pass@127.0.0.1:19080"})
        )
        results, warnings, _ = await adapter.search(query="бумага", limit=3, strategy="auto")
        return results, warnings, calls

    results, warnings, calls = asyncio.run(run())
    assert not warnings
    assert calls == {"hive": 0, "playwright": 1, "http": 0}
    assert len(results) == 1


def test_playwright_proxy_normalizes_socks5h_and_credentials():
    adapter = OzonAdapter(
        Settings(proxies={"ozon": "socks5h://user:p%40ss@[2001:db8::1]:19080"})
    )

    assert adapter._playwright_proxy() == {
        "server": "socks5://[2001:db8::1]:19080",
        "username": "user",
        "password": "p@ss",
    }
