from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from marketplaces_mcp.adapters import OzonAdapter, YandexMarketAdapter
from marketplaces_mcp.core.artifacts import create_artifact, read_artifact
from marketplaces_mcp.core.config import get_settings
from marketplaces_mcp.core.matching import group_product_results
from marketplaces_mcp.core.models import CompareResponse, OfferGroup, ProductResult, SearchResponse


REQUIRED_TOOLS = [
    "marketplaces_search",
    "ozon_search",
    "yandex_market_search",
    "marketplaces_compare",
    "marketplaces_product_details",
    "marketplaces_get_artifact",
]


mcp = FastMCP("marketplaces-mcp")
_settings = get_settings()
_adapters = {
    "ozon": OzonAdapter(_settings),
    "yandex_market": YandexMarketAdapter(_settings),
}


def _as_marketplace_list(raw: list[str] | None) -> list[str]:
    if raw is None:
        return list(_adapters.keys())
    result = []
    for item in raw:
        if item in _adapters:
            result.append(item)
    return result


@mcp.tool()
async def marketplaces_search(
    query: str,
    marketplaces: list[str] | None = None,
    limit: int = 10,
    strategy: str = "auto",
):
    marketplaces = _as_marketplace_list(marketplaces)
    warnings: list[str] = []
    all_results: list[ProductResult] = []
    used_urls: list[str] = []

    for key in marketplaces:
        adapter = _adapters[key]
        results, adapter_warnings, search_url = await adapter.search(
            query=query,
            limit=limit,
            strategy=strategy,
        )
        warnings.extend(adapter_warnings)
        used_urls.append(search_url)
        all_results.extend(results)

    all_results.sort(key=lambda item: (item.price is None, item.price or 0.0))
    all_results = all_results[:limit]

    response = SearchResponse(
        query=query,
        marketplaces=marketplaces,
        results=all_results,
        warnings=sorted(set(warnings)),
        tokens_estimate=_estimate_tokens(query, len(all_results)),
    )
    response.artifact_id = create_artifact({
        "type": "search",
        "query": query,
        "marketplaces": marketplaces,
        "search_urls": used_urls,
        "strategy": strategy,
        "results": [item.model_dump() for item in response.results],
    })

    return response


@mcp.tool()
async def ozon_search(query: str, limit: int = 10, strategy: str = "auto"):
    results, warnings, search_url = await _adapters["ozon"].search(query=query, limit=limit, strategy=strategy)
    response = SearchResponse(
        query=query,
        marketplaces=["ozon"],
        results=results[:limit],
        warnings=warnings,
    )
    response.artifact_id = create_artifact(
        {
            "type": "search",
            "query": query,
            "marketplaces": ["ozon"],
            "search_urls": [search_url],
            "strategy": strategy,
            "results": [item.model_dump() for item in response.results],
        }
    )
    return response


@mcp.tool()
async def yandex_market_search(query: str, limit: int = 10, strategy: str = "auto"):
    results, warnings, search_url = await _adapters["yandex_market"].search(
        query=query,
        limit=limit,
        strategy=strategy,
    )
    response = SearchResponse(
        query=query,
        marketplaces=["yandex_market"],
        results=results[:limit],
        warnings=warnings,
    )
    response.artifact_id = create_artifact(
        {
            "type": "search",
            "query": query,
            "marketplaces": ["yandex_market"],
            "search_urls": [search_url],
            "strategy": strategy,
            "results": [item.model_dump() for item in response.results],
        }
    )
    return response


@mcp.tool()
async def marketplaces_compare(
    query: str,
    limit_per_marketplace: int = 10,
    strategy: str = "auto",
):
    warnings: list[str] = []
    all_results: list[ProductResult] = []
    search_urls: list[str] = []
    for adapter in _adapters.values():
        results, adapter_warnings, search_url = await adapter.search(
            query=query,
            limit=limit_per_marketplace,
            strategy=strategy,
        )
        warnings.extend(adapter_warnings)
        search_urls.append(search_url)
        all_results.extend(results)

    groups_internal = group_product_results(all_results, similarity_threshold=0.4)
    groups_for_response: list[OfferGroup] = []
    low_confidence_warnings: list[str] = []

    for index, group in enumerate(groups_internal, start=1):
        offers = sorted(
            group.offers,
            key=lambda item: (item.price is None, item.price or 0.0),
        )
        groups_for_response.append(
            OfferGroup(
                canonical_title=group.canonical_title,
                offers=offers,
                confidence=group.confidence,
            )
        )
        if group.confidence < 0.35 and len(group.offers) > 1:
            low_confidence_warnings.append(f"LOW_CONFIDENCE_GROUP_{index}")

    best_offers = [group.offers[0] for group in groups_for_response if group.offers]
    best_offers.sort(key=lambda item: (item.price is None, item.price or 0.0))

    response = CompareResponse(
        query=query,
        groups=groups_for_response,
        best_offers=best_offers,
        warnings=sorted(set(warnings + low_confidence_warnings)),
    )
    response.artifact_id = create_artifact(
        {
            "type": "compare",
            "query": query,
            "limit_per_marketplace": limit_per_marketplace,
            "strategy": strategy,
            "search_urls": search_urls,
            "groups": [group.model_dump() for group in response.groups],
            "best_offers": [offer.model_dump() for offer in response.best_offers],
        }
    )
    return response


@mcp.tool()
async def marketplaces_product_details(url: str, strategy: str = "auto"):
    marketplace = _detect_marketplace(url)
    if marketplace not in _adapters:
        response = SearchResponse(
            query=url,
            marketplaces=["unknown"],
            results=[],
            warnings=["UNKNOWN_MARKETPLACE"],
        )
        response.artifact_id = create_artifact(
            {
                "type": "product_details",
                "url": url,
                "strategy": strategy,
                "status": "unsupported",
                "warnings": response.warnings,
            }
        )
        return response

    adapter = _adapters[marketplace]
    product, warnings, _ = await adapter.product_details(url=url, strategy=strategy)
    response = SearchResponse(
        query=url,
        marketplaces=[marketplace],
        results=[product] if product else [],
        warnings=warnings or [],
    )
    response.artifact_id = create_artifact(
        {
            "type": "product_details",
            "url": url,
            "marketplace": marketplace,
            "strategy": strategy,
            "result": product.model_dump() if product else None,
        }
    )
    return response


@mcp.tool()
async def marketplaces_get_artifact(artifact_id: str, name: str = "content.json"):
    return read_artifact(artifact_id, name=name)


def _detect_marketplace(url: str) -> str:
    lower = url.lower()
    if "ozon.ru" in lower:
        return "ozon"
    if "market.yandex.ru" in lower or "yandex" in lower:
        return "yandex_market"
    return "unknown"


def _estimate_tokens(query: str, results_count: int) -> int:
    return len(query) + results_count * 15


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
