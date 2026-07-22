#!/usr/bin/env python3
"""Read-only live canary for retail adapters and one explicit Avito request."""

from __future__ import annotations

import argparse
import asyncio
import json

from marketplaces_mcp.adapters import AvitoAdapter, OzonAdapter, WildberriesAdapter, YandexMarketAdapter


async def run(
    query: str,
    limit: int,
    include_details: bool,
    avito_query: str | None = None,
    avito_url: str | None = None,
    retail: bool = True,
) -> dict[str, object]:
    adapters = {
        "ozon": OzonAdapter(),
        "yandex_market": YandexMarketAdapter(),
        "wildberries": WildberriesAdapter(),
    }
    output: dict[str, object] = {"query": query, "search": {}, "details": {}}
    first_urls: dict[str, str] = {}
    if retail:
        for name, adapter in adapters.items():
            products, warnings, search_url = await adapter.search(query=query, limit=limit)
            output["search"][name] = {
                "search_url": search_url,
                "warnings": warnings,
                "results": [product.model_dump(mode="json") for product in products],
            }
            if products:
                first_urls[name] = products[0].url

    if include_details:
        for name in ("ozon", "yandex_market"):
            if name not in first_urls:
                continue
            product, warnings, url = await adapters[name].product_details(first_urls[name])
            output["details"][name] = {
                "url": url,
                "warnings": warnings,
                "result": product.model_dump(mode="json") if product else None,
            }

    if avito_query:
        products, warnings, search_url = await AvitoAdapter().search(query=avito_query, limit=limit)
        output["avito"] = {
            "mode": "search",
            "search_url": search_url,
            "warnings": warnings,
            "results": [product.model_dump(mode="json") for product in products],
        }
    elif avito_url:
        product, warnings, normalized_url = await AvitoAdapter().product_details(avito_url)
        output["avito"] = {
            "mode": "details",
            "url": normalized_url,
            "warnings": warnings,
            "result": product.model_dump(mode="json") if product else None,
        }
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?", default="детский наматрасник 60x120 TPU")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--details", action="store_true")
    parser.add_argument("--avito-only", action="store_true")
    avito = parser.add_mutually_exclusive_group()
    avito.add_argument("--avito-query")
    avito.add_argument("--avito-url")
    args = parser.parse_args()
    result = asyncio.run(
        run(
            args.query,
            args.limit,
            args.details,
            avito_query=args.avito_query,
            avito_url=args.avito_url,
            retail=not args.avito_only,
        )
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
