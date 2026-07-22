import asyncio
import inspect

from marketplaces_mcp.mcp_server.server import REQUIRED_TOOLS
from marketplaces_mcp.mcp_server.server import (
    marketplaces_compare,
    marketplaces_get_artifact,
    marketplaces_product_details,
    marketplaces_product_reviews,
    marketplaces_search,
    avito_search,
    ozon_search,
    wildberries_search,
    yandex_market_search,
)


def _slugify(query: str) -> str:
    import re
    normalized = re.sub(r"\s+", "_", str(query).strip().lower())
    normalized = re.sub(r"[^0-9а-яА-Яa-zA-ZёЁ_-]", "", normalized)
    return normalized or "default"


def test_tools_registered_and_fixture_search_works(tmp_path, monkeypatch):
    required = {
        "marketplaces_search",
        "ozon_search",
        "wildberries_search",
        "yandex_market_search",
        "avito_search",
        "marketplaces_compare",
        "marketplaces_product_details",
        "marketplaces_product_reviews",
        "marketplaces_get_artifact",
    }
    assert required.issubset(set(REQUIRED_TOOLS))

    query = "бумага a4"
    slug = _slugify(query)
    fixture_dir = tmp_path / "fixtures"
    ozon_dir = fixture_dir / "ozon"
    wildberries_dir = fixture_dir / "wildberries"
    yandex_dir = fixture_dir / "yandex_market"
    ozon_dir.mkdir(parents=True)
    wildberries_dir.mkdir(parents=True)
    yandex_dir.mkdir(parents=True)
    fixture_html = (
        "<div class='tile-root'><a href='/product/ozon-smoke-123/' title='Ozon smoke fixture'>"
        "Ozon smoke fixture</a><span class='price'>100 ₽</span></div>"
    )
    (ozon_dir / f"{slug}.html").write_text(fixture_html, encoding="utf-8")
    (wildberries_dir / f"{slug}.html").write_text(
        "<article class='product-card'><a href='/catalog/5148062/detail.aspx' "
        "aria-label='Wildberries smoke fixture'></a><span>110 ₽</span></article>",
        encoding="utf-8",
    )
    (yandex_dir / f"{slug}.html").write_text(
        "<html><body><div data-zone-name='productSnippet'>"
        "<a data-auto='snippet-link' href='/card/yandex-smoke/102236642854'>Yandex smoke fixture</a>"
        "<span>Цена с картой Яндекс Пэй 120 ₽</span></div></body></html>",
        encoding="utf-8",
    )

    monkeypatch.setenv("MARKETPLACES_FIXTURES_DIR", str(fixture_dir))

    async def run_search():
        search_response = await marketplaces_search(
            query=query,
            marketplaces=["ozon"],
            limit=5,
            strategy="fixture",
        )
        yandex_response = await yandex_market_search(query=query, limit=2, strategy="fixture")
        compare_response = await marketplaces_compare(query=query, limit_per_marketplace=2, strategy="fixture")
        details_response = await marketplaces_product_details(url="https://www.ozon.ru/product/1", strategy="fixture")
        artifact_payload = await marketplaces_get_artifact(search_response.artifact_id)
        return (
            search_response,
            yandex_response,
            compare_response,
            details_response,
            artifact_payload,
        )

    search_response, yandex_response, compare_response, details_response, artifact_payload = asyncio.run(run_search())
    assert search_response.query == query
    assert search_response.marketplaces == ["ozon"]
    assert search_response.results
    assert search_response.results[0].marketplace == "ozon"
    assert search_response.artifact_id
    assert artifact_payload["type"] == "search"

    assert yandex_response.marketplaces == ["yandex_market"]

    assert len(compare_response.groups) >= 1

    assert details_response.marketplaces == ["ozon"]
    assert inspect.iscoroutinefunction(marketplaces_product_reviews)
    assert inspect.iscoroutinefunction(avito_search)
    assert inspect.iscoroutinefunction(marketplaces_get_artifact)
