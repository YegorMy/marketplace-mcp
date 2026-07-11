from __future__ import annotations

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
import asyncio
