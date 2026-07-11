from __future__ import annotations

import asyncio
import pytest

from marketplaces_mcp.adapters import OzonAdapter, YandexMarketAdapter


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

YANDEX_AIR75_TEXT_FIXTURE_HTML = """
<html><body>
  <div>
    Беспроводная механическая клавиатура Nuphy QMK, AIR75v2, Ionic White, RGB Hot Swap Red Switch Назначение: для настольного компьютера Беспроводная клавиатура: да Интерфейс подключения: USB Type-C Подсветка: подсветка клавиш Цвет товара: белый Цена с картой Яндекс Пэй 12465 ₽ вместо 12 465 ₽ Пэй Рейтинг товара: 5.0 из 5 Оценок: (12) · 75 купили 5.0 (12) · 75 купили Послезавтра , курьер Доставка магазина Холодильник.ру В корзину
  </div>
  <div>
    Беспроводная механическая клавиатура Nuphy QMK, AIR75v2, Basalt Black, RGB, Hot Swap, Aloe Switch (AIR75v2-BB-21) Назначение: игровая ... Общее количество клавиш: 84 Цена с картой Яндекс Пэй 12873 ₽ вместо 12 873 ₽ Пэй Рейтинг товара: 5.0 из 5 Оценок: (1) · 5 купили 5.0 (1) · 5 купили Послезавтра , курьер Доставка магазина Холодильник.ру В корзину
  </div>
</body></html>
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


def test_yandex_visible_text_fixture_parsing():
    async def run():
        adapter = YandexMarketAdapter()
        results, warnings, _ = await adapter.search(
            query="NuPhy Air75 V2",
            limit=3,
            strategy="fixture",
            fixture_html=YANDEX_AIR75_TEXT_FIXTURE_HTML,
        )
        return results, warnings

    results, warnings = asyncio.run(run())
    assert not warnings
    assert len(results) == 2
    first = results[0]
    assert first.marketplace == "yandex_market"
    assert first.price == 12465.0
    assert first.rating == 5.0
    assert first.reviews_count == 12
    assert first.raw["orders_count"] == 75
    assert first.delivery_hint == "Послезавтра, курьер"


def test_yandex_default_backend_uses_hive_web_visible_text(monkeypatch):
    async def run():
        calls = {"hive": 0}

        async def fake_hive_web(self, _url: str):
            calls["hive"] += 1
            return YANDEX_AIR75_TEXT_FIXTURE_HTML

        monkeypatch.setenv("MARKETPLACES_WEB_BACKEND", "hive_web")
        monkeypatch.setattr(YandexMarketAdapter, "_fetch_with_hive_web", fake_hive_web)
        adapter = YandexMarketAdapter()
        results, warnings, _ = await adapter.search(query="NuPhy Air75 V2", limit=3, strategy="auto")
        return results, warnings, calls["hive"]

    results, warnings, calls = asyncio.run(run())
    assert not warnings
    assert calls == 1
    assert len(results) == 2


def test_yandex_hive_web_failure_in_strict_mode_does_not_fallback(monkeypatch):
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

        monkeypatch.setenv("MARKETPLACES_WEB_BACKEND", "hive_web")
        monkeypatch.setattr(YandexMarketAdapter, "_fetch_with_hive_web", failing_hive_web)
        monkeypatch.setattr(YandexMarketAdapter, "_fetch_with_playwright", legacy_called)
        monkeypatch.setattr(YandexMarketAdapter, "_fetch_with_http", legacy_http)

        results, warnings, _ = await YandexMarketAdapter().search(
            query="NuPhy Air75 V2",
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
            query="NuPhy Air75 V2",
            limit=3,
            strategy="fixture",
            fixture_html=YANDEX_AIR75_TEXT_FIXTURE_HTML,
        )
        return results, warnings, calls["hive"]

    results, warnings, calls = asyncio.run(run())
    assert not warnings
    assert calls == 0
    assert len(results) == 2
