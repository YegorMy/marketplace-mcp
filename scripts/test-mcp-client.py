#!/usr/bin/env python3
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_TOOLS = {
    "avito_search",
    "avito_game_search",
    "avito_access_status",
    "ozon_tours_access_status",
    "ozon_travel_tours_search",
    "ozon_travel_tour_details",
    "package_tours_search",
    "marketplaces_search",
    "ozon_search",
    "wildberries_search",
    "yandex_market_search",
    "marketplaces_compare",
    "marketplaces_product_details",
    "marketplaces_product_reviews",
    "marketplaces_get_artifact",
    "ozon_travel_flights_search",
    "ozon_travel_hotels_search",
    "ozon_travel_hotel_details",
}


def _write_fixture(root: Path) -> None:
    slug = "бумага_a4"
    (root / "ozon").mkdir(parents=True)
    (root / "wildberries").mkdir(parents=True)
    (root / "yandex_market").mkdir(parents=True)
    (root / "ozon_travel").mkdir(parents=True)
    (root / "ozon" / f"{slug}.html").write_text(
        "<div class='tile-root'><a href='/product/1' title='Бумага A4 500 листов'>Бумага A4 500 листов</a><span class='price'>399 ₽</span></div>",
        encoding="utf-8",
    )
    (root / "wildberries" / f"{slug}.html").write_text(
        "<article class='product-card'><a href='/catalog/5148062/detail.aspx' aria-label='Бумага A4 Wildberries'></a><span class='price'>409 ₽</span></article>",
        encoding="utf-8",
    )
    (root / "yandex_market" / f"{slug}.html").write_text(
        "<div data-zone-name='productSnippet'><a data-auto='snippet-link' href='/card/yandex-smoke/102236642854'>Бумага A4 Яндекс</a><span>Цена с картой Яндекс Пэй 429 ₽</span></div>",
        encoding="utf-8",
    )
    (root / "ozon_travel" / "flight_mow_led_2030-05-10.html").write_text(
        "<article><div>Победа</div><div>07:35 — 09:05</div><div>Прямой 1ч 30м</div>"
        "<div>Без багажа</div><a href='/travel/flight/'>от 2 679 ₽</a></article>",
        encoding="utf-8",
    )
    (root / "ozon_travel" / "hotel_сочи_2030-05-10_2030-05-12.html").write_text(
        "<article><a href='/travel/hotels/product/hotel-volna-1001/'>Отель Волна, 4*</a>"
        "<div>Сочи • 900 м до центра 4.8 250 отзывов Wi-Fi от 5 000 ₽</div></article>",
        encoding="utf-8",
    )


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="marketplaces-mcp-fixtures-") as tmp:
        fixture_dir = Path(tmp)
        _write_fixture(fixture_dir)
        env = os.environ.copy()
        env["MARKETPLACES_FIXTURES_DIR"] = str(fixture_dir)

        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "marketplaces_mcp"],
            env=env,
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                missing = sorted(REQUIRED_TOOLS - names)
                if missing:
                    raise SystemExit(f"missing MCP tools: {missing}")
                result = await session.call_tool(
                    "marketplaces_search",
                    {"query": "бумага a4", "limit": 2, "strategy": "fixture"},
                )
                flight_result = await session.call_tool(
                    "ozon_travel_flights_search",
                    {
                        "origin": "MOW",
                        "destination": "LED",
                        "departure_date": "2030-05-10",
                        "strategy": "fixture",
                    },
                )
                hotel_result = await session.call_tool(
                    "ozon_travel_hotels_search",
                    {
                        "destination": "Сочи",
                        "check_in": "2030-05-10",
                        "check_out": "2030-05-12",
                        "include_rates": False,
                        "strategy": "fixture",
                    },
                )
                access_result = await session.call_tool("ozon_tours_access_status", {})
                assert not access_result.isError
                assert json.loads(access_result.content[0].text)["search_supported"] is True
                assert not any(result.isError for result in (result, flight_result, hotel_result))
                for tool_name, arguments in (
                    ("ozon_travel_tours_search", {"departure_date": "not-a-date"}),
                    ("ozon_travel_tours_search", {"search_url": "https://www.ozon.ru/travel/tours/search?fromCity=100001"}),
                    ("ozon_travel_tour_details", {"search_url": "invalid", "hotel_name": "Fixture"}),
                ):
                    rejected = await session.call_tool(tool_name, arguments)
                    assert not rejected.isError
                    payload = json.loads(rejected.content[0].text)
                    assert payload["offers"] == []
                    assert payload["warnings"] == ["INVALID_TOUR_REQUEST"]
                    assert payload["source_url"] == "https://www.ozon.ru/travel/tours/"
                print(
                    json.dumps(
                        {
                            "tool_count": len(names),
                            "tools": sorted(names),
                            "retail_result": result.content[0].text[:1000],
                            "flight_result": flight_result.content[0].text[:1000],
                            "hotel_result": hotel_result.content[0].text[:1000],
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )


def cli() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    cli()
