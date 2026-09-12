from __future__ import annotations

import asyncio
from datetime import date
from urllib.parse import urlsplit

from mcp.server.fastmcp import FastMCP

from marketplaces_mcp.adapters import (
    AvitoAdapter,
    OzonAdapter,
    OzonTravelAdapter,
    PackageToursAdapter,
    WildberriesAdapter,
    YandexMarketAdapter,
)
from marketplaces_mcp.core.ozon_tours_access import OzonToursAccess
from marketplaces_mcp.core.ozon_tours_browser import OzonToursBrowser
from marketplaces_mcp.adapters.ozon_tours import OzonToursAdapter, build_search_url, search_context
from marketplaces_mcp.core.artifacts import create_artifact, read_artifact
from marketplaces_mcp.core.config import get_settings
from marketplaces_mcp.core.matching import group_product_results
from marketplaces_mcp.core.models import (
    CompareResponse,
    FlightSearchResponse,
    HotelSearchResponse,
    OfferGroup,
    OzonTourResponse,
    ProductResult,
    ReviewsResponse,
    SearchResponse,
    TourSearchResponse,
)
from marketplaces_mcp.core.reviews import fetch_reviews
from marketplaces_mcp.core.game_search import search_game_offers
from marketplaces_mcp.core.price_evidence import is_public_price, price_sort_key

REQUIRED_TOOLS = [
    "marketplaces_search",
    "ozon_search",
    "wildberries_search",
    "yandex_market_search",
    "avito_search",
    "avito_game_search",
    "avito_access_status",
    "marketplaces_compare",
    "marketplaces_product_details",
    "marketplaces_product_reviews",
    "marketplaces_get_artifact",
    "ozon_travel_flights_search",
    "ozon_travel_hotels_search",
    "ozon_travel_hotel_details",
    "package_tours_search",
    "ozon_tours_access_status",
    "ozon_travel_tours_search",
    "ozon_travel_tour_details",
]


mcp = FastMCP("marketplaces-mcp")
_settings = get_settings()
_adapters = {
    "ozon": OzonAdapter(_settings),
    "wildberries": WildberriesAdapter(_settings),
    "yandex_market": YandexMarketAdapter(_settings),
    "avito": AvitoAdapter(_settings),
}
_default_marketplaces = ["ozon", "wildberries", "yandex_market"]
_travel_adapter = OzonTravelAdapter(_settings)
_package_tours_adapter = PackageToursAdapter()


_tours_browser = OzonToursBrowser(_settings.camofox_url)
_tours_access = OzonToursAccess(_tours_browser)
_ozon_package_adapter = OzonToursAdapter(_tours_browser, _tours_access)


@mcp.tool()
async def ozon_tours_access_status(probe: bool = False, inspect_tab: bool = False):
    """Read last Ozon tours access evidence. By default makes no site requests.

    probe=True permits one normal browser check only when the shared 30-minute
    cooldown allows it. inspect_tab=True only reads the retained browser tab,
    even during cooldown: use after manual CAPTCHA completion without navigating.
    Availability never implies package search support.
    """
    return await _tours_access.status(probe=probe, inspect_tab=inspect_tab)



@mcp.tool()
async def ozon_travel_tours_search(
    origin: str = "LED", destination: str = "ОАЭ", departure_date: str = "",
    min_nights: int = 5, max_nights: int = 9, adults: int = 2,
    child_ages: list[int] | None = None, rooms: int = 1,
    all_inclusive_only: bool = True, limit: int = 10,
) -> OzonTourResponse:
    """Search actual Ozon package tours in the retained desktop Camofox browser.

    Currently verified LED to UAE, one room. Include infant age 0 in child_ages.
    One exact departure date and at most five stay lengths (5–9 then 10–12).
    Returns hotel leads, never treats search-card prices as matching meal prices.
    Call ozon_travel_tour_details for serious candidates. No booking or payment.
    """
    kwargs = dict(
        origin=origin, destination=destination, departure_date=departure_date,
        min_nights=min_nights, max_nights=max_nights, adults=adults,
        child_ages=child_ages, rooms=rooms, all_inclusive_only=all_inclusive_only,
    )
    try:
        source_url = build_search_url(**kwargs)
    except ValueError:
        return OzonTourResponse(source_url="https://www.ozon.ru/travel/tours/",
                                warnings=["INVALID_TOUR_REQUEST"])
    return await _call_tour_tool(_ozon_package_adapter.search(**kwargs, limit=limit),
                                source_url=source_url, timeout=150)


@mcp.tool()
async def ozon_travel_tour_details(search_url: str, hotel_name: str,
                                   all_inclusive_only: bool = True, limit: int = 20) -> OzonTourResponse:
    """Read exact Ozon room/meal/operator package quotes for a current search lead.

    Pass source_url and exact hotel_name from ozon_travel_tours_search. Opens only
    room selection, stops before selecting a flight, reservation or payment.
    Room-page meal filters are checked independently: Ozon search-card prices
    can reflect breakfast even when all-inclusive was selected.
    """
    try:
        search_context(search_url)
    except ValueError:
        return OzonTourResponse(source_url="https://www.ozon.ru/travel/tours/",
                                warnings=["INVALID_TOUR_REQUEST"])
    return await _call_tour_tool(_ozon_package_adapter.details(
        search_url=search_url, hotel_name=hotel_name,
        all_inclusive_only=all_inclusive_only, limit=limit,
    ), source_url=search_url, timeout=110)


async def _call_tour_tool(operation, *, source_url: str, timeout: float) -> OzonTourResponse:
    try:
        payload = await asyncio.wait_for(operation, timeout=timeout)
        return OzonTourResponse.model_validate(payload)
    except Exception as exc:
        # CancelledError is intentionally not caught: cancellation must release
        # the adapter's lock and stop the browser workflow.
        if isinstance(exc, BlockingIOError):
            warnings = ["OZON_TOURS_REQUEST_IN_PROGRESS"]
        elif str(exc) in {"OZON_TOURS_CAPTCHA_REQUIRED", "OZON_TOURS_BLOCKED"}:
            warnings = [str(exc), "CAPTCHA_OR_BLOCKED"]
        elif isinstance(exc, ValueError):
            warnings = ["OZON_TOURS_CONTEXT_UNVERIFIED"]
        else:
            warnings = [f"OZON_TOURS_FAILED_{type(exc).__name__}"]
        return OzonTourResponse(source_url=source_url, warnings=warnings,
                                access=_tours_access.read())


async def _safe_search(adapter, **kwargs):
    kwargs["limit"] = max(1, min(int(kwargs.get("limit", 10)), 30))
    try:
        return await asyncio.wait_for(adapter.search(**kwargs), 150)
    except Exception as exc:
        return [], [f"{adapter.marketplace.upper()}_SEARCH_FAILED_{type(exc).__name__}"], adapter.build_search_url(kwargs["query"])


async def _safe_details(adapter, **kwargs):
    try:
        return await asyncio.wait_for(adapter.product_details(**kwargs), 150)
    except Exception as exc:
        return None, [f"{adapter.marketplace.upper()}_DETAILS_FAILED_{type(exc).__name__}"], kwargs["url"]


def _as_marketplace_list(raw: list[str] | None) -> list[str]:
    if raw is None:
        return list(_default_marketplaces)
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
        results, adapter_warnings, search_url = await _safe_search(adapter,
            query=query,
            limit=limit,
            strategy=strategy,
        )
        warnings.extend(adapter_warnings)
        used_urls.append(search_url)
        all_results.extend(results)

    all_results.sort(key=price_sort_key)
    all_results = all_results[:limit]

    response = SearchResponse(
        query=query,
        marketplaces=marketplaces,
        results=all_results,
        warnings=sorted(set(warnings)),
        tokens_estimate=_estimate_tokens(query, len(all_results)),
    )
    response.artifact_id = create_artifact(
        {
            "type": "search",
            "query": query,
            "marketplaces": marketplaces,
            "search_urls": used_urls,
            "strategy": strategy,
            "results": [item.model_dump() for item in response.results],
        }
    )

    return response


@mcp.tool()
async def ozon_search(query: str, limit: int = 10, strategy: str = "auto"):
    results, warnings, search_url = await _safe_search(_adapters["ozon"],
        query=query, limit=limit, strategy=strategy
    )
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
async def wildberries_search(query: str, limit: int = 10, strategy: str = "auto"):
    results, warnings, search_url = await _safe_search(_adapters["wildberries"],
        query=query,
        limit=limit,
        strategy=strategy,
    )
    response = SearchResponse(
        query=query,
        marketplaces=["wildberries"],
        results=results[:limit],
        warnings=sorted(set(warnings)),
    )
    response.artifact_id = create_artifact(
        {
            "type": "search",
            "query": query,
            "marketplaces": ["wildberries"],
            "search_urls": [search_url],
            "strategy": strategy,
            "results": [item.model_dump() for item in response.results],
        }
    )
    return response


@mcp.tool()
async def yandex_market_search(query: str, limit: int = 10, strategy: str = "auto"):
    results, warnings, search_url = await _safe_search(_adapters["yandex_market"],
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
async def avito_search(query: str, limit: int = 10, strategy: str = "auto"):
    results, warnings, search_url = await _safe_search(_adapters["avito"],
        query=query,
        limit=limit,
        strategy=strategy,
    )
    response = SearchResponse(
        query=query,
        marketplaces=["avito"],
        results=results[:limit],
        warnings=sorted(set(warnings)),
    )
    response.artifact_id = create_artifact(
        {
            "type": "search",
            "query": query,
            "marketplaces": ["avito"],
            "search_urls": [search_url],
            "strategy": strategy,
            "results": [item.model_dump() for item in response.results],
        }
    )
    return response


@mcp.tool()
async def avito_access_status():
    """Read Avito block reason and earliest retry time. No browser or index requests.

    A ready state permits a single normal probe; it never proves access or price.
    """
    return await _adapters["avito"].access_status()


@mcp.tool()
async def avito_game_search(game_title: str, max_price: float | None = None,
                           include_game_key_cards: bool = True, limit: int = 8,
                           verify_details: int = 2, strategy: str = "auto"):
    """Find Switch 2 physical games; separate cartridges from Game-Key Cards.

    Only eligible_offers have a matching title and verified live detail price.
    Digital codes, accounts, ambiguous lots and indexed prices cannot qualify.
    Stop on Avito cooldown. At most two detail reads, no purchases or messages.
    """
    return await search_game_offers(_adapters["avito"], game_title, max_price=max_price,
        include_game_key_cards=include_game_key_cards, limit=limit,
        verify_details=verify_details, strategy=strategy)


@mcp.tool()
async def ozon_travel_flights_search(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str | None = None,
    adults: int = 1,
    children: int = 0,
    infants: int = 0,
    cabin_class: str = "economy",
    direct_only: bool = False,
    sort: str = "price",
    limit: int = 10,
    strategy: str = "auto",
):
    """Search public Ozon Travel flight offers without booking or account actions."""
    results, warnings, source_url = await _travel_adapter.search_flights(
        origin,
        destination,
        departure_date,
        return_date,
        adults=adults,
        children=children,
        infants=infants,
        cabin_class=cabin_class,
        direct_only=direct_only,
        sort=sort,
        limit=limit,
        strategy=strategy,
    )
    response = FlightSearchResponse(
        origin=origin,
        destination=destination,
        departure_date=_safe_date(departure_date),
        return_date=_safe_date(return_date),
        adults=adults,
        children=children,
        infants=infants,
        cabin_class=cabin_class,
        results=results,
        warnings=warnings,
        source_url=source_url,
    )
    response.artifact_id = create_artifact(
        {
            "type": "ozon_travel_flight_search",
            "origin": origin,
            "destination": destination,
            "departure_date": departure_date,
            "return_date": return_date,
            "passengers": {"adults": adults, "children": children, "infants": infants},
            "cabin_class": cabin_class,
            "direct_only": direct_only,
            "sort": sort,
            "strategy": strategy,
            "source_url": source_url,
            "warnings": warnings,
            "results": [item.model_dump(mode="json") for item in results],
        }
    )
    return response


@mcp.tool()
async def ozon_travel_hotels_search(
    destination: str,
    check_in: str,
    check_out: str,
    adults: int = 2,
    rooms: int = 1,
    min_rating: float | None = None,
    stars: list[int] | None = None,
    max_total_price: float | None = None,
    sort: str = "price",
    include_rates: bool = True,
    limit: int = 10,
    strategy: str = "auto",
):
    """Search public Ozon Travel hotels for exact stay dates and guest count."""
    results, warnings, source_url = await _travel_adapter.search_hotels(
        destination,
        check_in,
        check_out,
        adults=adults,
        rooms=rooms,
        min_rating=min_rating,
        stars=stars,
        max_total_price=max_total_price,
        sort=sort,
        include_rates=include_rates,
        limit=limit,
        strategy=strategy,
    )
    parsed_check_in = _safe_date(check_in)
    parsed_check_out = _safe_date(check_out)
    response = HotelSearchResponse(
        destination=destination,
        check_in=parsed_check_in,
        check_out=parsed_check_out,
        nights=_stay_nights(parsed_check_in, parsed_check_out),
        adults=adults,
        rooms=rooms,
        results=results,
        warnings=warnings,
        source_url=source_url,
    )
    response.artifact_id = create_artifact(
        {
            "type": "ozon_travel_hotel_search",
            "destination": destination,
            "check_in": check_in,
            "check_out": check_out,
            "adults": adults,
            "rooms": rooms,
            "filters": {
                "min_rating": min_rating,
                "stars": stars,
                "max_total_price": max_total_price,
                "sort": sort,
            },
            "strategy": strategy,
            "source_url": source_url,
            "warnings": warnings,
            "results": [item.model_dump(mode="json") for item in results],
        }
    )
    return response


@mcp.tool()
async def ozon_travel_hotel_details(
    url: str,
    destination: str,
    check_in: str,
    check_out: str,
    adults: int = 2,
    rooms: int = 1,
    strategy: str = "auto",
):
    """Read one public Ozon Travel hotel page with rates for exact dates."""
    hotel, warnings = await _travel_adapter.hotel_details(
        url,
        destination=destination,
        check_in=check_in,
        check_out=check_out,
        adults=adults,
        rooms=rooms,
        strategy=strategy,
    )
    parsed_check_in = _safe_date(check_in)
    parsed_check_out = _safe_date(check_out)
    response = HotelSearchResponse(
        destination=destination,
        check_in=parsed_check_in,
        check_out=parsed_check_out,
        nights=_stay_nights(parsed_check_in, parsed_check_out),
        adults=adults,
        rooms=rooms,
        results=[hotel] if hotel else [],
        warnings=warnings,
        source_url=url,
    )
    response.artifact_id = create_artifact(
        {
            "type": "ozon_travel_hotel_details",
            "url": url,
            "destination": destination,
            "check_in": check_in,
            "check_out": check_out,
            "adults": adults,
            "rooms": rooms,
            "strategy": strategy,
            "warnings": warnings,
            "result": hotel.model_dump(mode="json") if hotel else None,
        }
    )
    return response


@mcp.tool()
async def package_tours_search(
    origin: str,
    destination: str,
    departure_date_from: str,
    departure_date_to: str,
    min_nights: int = 5,
    max_nights: int = 12,
    adults: int = 2,
    children: int = 0,
    infants: int = 0,
    child_ages: list[int] | None = None,
    infant_ages: list[int] | None = None,
    rooms: int = 1,
    all_inclusive_only: bool = False,
    stars: list[int] | None = None,
    sort: str = "value",
    limit: int = 30,
):
    """Search independent 1001tur flight+hotel quotes, never Ozon prices.

    Requires exact returned dates, party, ages, meals, and included airfare.
    One room only. Infants default to age 0; specify infant_ages for age 1.
    Results cover a partial supplier snapshot and need price reconfirmation.
    This tool does not query Ozon or diagnose its availability.
    """
    results, warnings, source_url = await _package_tours_adapter.search(
        origin=origin,
        destination=destination,
        departure_date_from=departure_date_from,
        departure_date_to=departure_date_to,
        min_nights=min_nights,
        max_nights=max_nights,
        adults=adults,
        children=children,
        infants=infants,
        child_ages=child_ages or [],
        infant_ages=([0] * infants if infant_ages is None else infant_ages),
        rooms=rooms,
        all_inclusive_only=all_inclusive_only,
        stars=stars,
        sort=sort,
        limit=limit,
    )
    response = TourSearchResponse(
        origin=origin,
        destination=destination,
        departure_date_from=date.fromisoformat(departure_date_from),
        departure_date_to=date.fromisoformat(departure_date_to),
        min_nights=min_nights,
        max_nights=max_nights,
        adults=adults,
        children=children,
        infants=infants,
        child_ages=child_ages or [],
        infant_ages=([0] * infants if infant_ages is None else infant_ages),
        rooms=rooms,
        meal_plan="all_inclusive" if all_inclusive_only else None,
        results=results,
        warnings=warnings,
        source_url=source_url,
    )
    response.artifact_id = create_artifact(
        {
            "type": "package_tours_search",
            "requested_provider": "1001tur",
            "origin": origin,
            "destination": destination,
            "departure_date_from": departure_date_from,
            "departure_date_to": departure_date_to,
            "min_nights": min_nights,
            "max_nights": max_nights,
            "passengers": {"adults": adults, "children": children, "infants": infants},
            "child_ages": child_ages or [],
            "infant_ages": [0] * infants if infant_ages is None else infant_ages,
            "rooms": rooms,
            "all_inclusive_only": all_inclusive_only,
            "stars": stars,
            "sort": sort,
            "source_url": source_url,
            "warnings": warnings,
            "results": [item.model_dump(mode="json") for item in results],
        }
    )
    return response


@mcp.tool()
async def marketplaces_compare(
    query: str,
    limit_per_marketplace: int = 10,
    strategy: str = "auto",
    include_avito: bool = False,
):
    warnings: list[str] = []
    all_results: list[ProductResult] = []
    search_urls: list[str] = []
    adapter_keys = list(_default_marketplaces)
    if include_avito:
        adapter_keys.append("avito")
    for key in adapter_keys:
        adapter = _adapters[key]
        results, adapter_warnings, search_url = await _safe_search(adapter,
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
            key=price_sort_key,
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

    best_offers = [next((offer for offer in group.offers if is_public_price(offer)), None)
                   for group in groups_for_response]
    best_offers = [offer for offer in best_offers if offer is not None]
    best_offers.sort(key=price_sort_key)
    if any(not is_public_price(offer) for offer in all_results):
        warnings.append("NON_PUBLIC_PRICES_EXCLUDED_FROM_BEST_OFFERS")

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
    product, warnings, _ = await _safe_details(adapter, url=url, strategy=strategy)
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
async def marketplaces_product_reviews(url: str, limit: int = 20):
    marketplace = _detect_marketplace(url)
    if marketplace not in _adapters:
        return ReviewsResponse(
            url=url,
            marketplace="unknown",
            warnings=["UNKNOWN_MARKETPLACE"],
        )
    try:
        reviews, warnings, review_url, total, rating = await asyncio.wait_for(
            fetch_reviews(_adapters[marketplace], url, max(1, min(limit, 30))), 150)
    except Exception as exc:
        return ReviewsResponse(url=url, marketplace=marketplace,
                               warnings=[f"REVIEWS_FAILED_{type(exc).__name__}"])
    response = ReviewsResponse(
        url=review_url,
        marketplace=marketplace,
        total_reviews=total,
        rating=rating,
        reviews=reviews,
        warnings=warnings,
    )
    response.artifact_id = create_artifact(
        {
            "type": "product_reviews",
            "url": review_url,
            "marketplace": marketplace,
            "total_reviews": total,
            "rating": rating,
            "warnings": warnings,
            "reviews": [review.model_dump() for review in reviews],
        }
    )
    return response


@mcp.tool()
async def marketplaces_get_artifact(artifact_id: str, name: str = "content.json"):
    return read_artifact(artifact_id, name=name)


def _detect_marketplace(url: str) -> str:
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in {None, 443}:
            return "unknown"
        return {"ozon.ru": "ozon", "www.ozon.ru": "ozon",
                "wildberries.ru": "wildberries", "www.wildberries.ru": "wildberries",
                "market.yandex.ru": "yandex_market", "avito.ru": "avito",
                "www.avito.ru": "avito"}.get(parsed.hostname, "unknown")
    except ValueError:
        return "unknown"


def _estimate_tokens(query: str, results_count: int) -> int:
    return len(query) + results_count * 15


def _safe_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _stay_nights(check_in: date | None, check_out: date | None) -> int | None:
    if check_in is None or check_out is None:
        return None
    nights = (check_out - check_in).days
    return nights if nights > 0 else None


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
