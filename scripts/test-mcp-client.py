#!/usr/bin/env python3
import asyncio
import json
import os
import tempfile
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_TOOLS = {
    "avito_search",
    "marketplaces_search",
    "ozon_search",
    "wildberries_search",
    "yandex_market_search",
    "marketplaces_compare",
    "marketplaces_product_details",
    "marketplaces_product_reviews",
    "marketplaces_get_artifact",
}


def _write_fixture(root: Path) -> None:
    slug = "бумага_a4"
    (root / "ozon").mkdir(parents=True)
    (root / "wildberries").mkdir(parents=True)
    (root / "yandex_market").mkdir(parents=True)
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


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="marketplaces-mcp-fixtures-") as tmp:
        fixture_dir = Path(tmp)
        _write_fixture(fixture_dir)
        env = os.environ.copy()
        env["MARKETPLACES_FIXTURES_DIR"] = str(fixture_dir)

        params = StdioServerParameters(
            command="uv",
            args=["run", "--project", str(ROOT), "marketplaces-mcp"],
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
                print(json.dumps({"tool_count": len(names), "tools": sorted(names), "result": result.content[0].text[:1000]}, ensure_ascii=False, indent=2))


def cli() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    cli()
