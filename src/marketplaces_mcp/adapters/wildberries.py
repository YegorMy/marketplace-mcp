from __future__ import annotations

from typing import Any

import httpx
import re
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from marketplaces_mcp.adapters.base import BaseAdapter
from marketplaces_mcp.core.models import ProductResult
from marketplaces_mcp.core.normalize import parse_price


class WildberriesAdapter(BaseAdapter):
    marketplace = "wildberries"
    search_url_template = "https://www.wildberries.ru/catalog/0/search.aspx?search={query}"
    discovery_domain = "wildberries.ru/catalog"
    product_url_patterns = (r"https://(?:www\.)?wildberries\.ru/catalog/\d+/detail\.aspx$",)

    async def search(
        self,
        query: str,
        limit: int = 10,
        strategy: str = "auto",
        fixture_html: str | None = None,
    ) -> tuple[list[ProductResult], list[str], str]:
        if strategy == "fixture":
            return await super().search(
                query=query,
                limit=limit,
                strategy=strategy,
                fixture_html=fixture_html,
            )

        search_url = self.build_search_url(query)
        api_products, api_warnings = await self._search_with_public_api(query)
        if api_products:
            return api_products[:limit], api_warnings, search_url

        products, warnings, source_url = await super().search(
            query=query,
            limit=limit,
            strategy=strategy,
            fixture_html=fixture_html,
        )
        return products, sorted(set(api_warnings + warnings)), source_url

    async def product_details(
        self,
        url: str,
        strategy: str = "auto",
        fixture_html: str | None = None,
    ) -> tuple[ProductResult | None, list[str], str]:
        normalized = self.normalize_product_url(url)
        if not self.is_product_url(normalized):
            return None, ["INVALID_PRODUCT_URL"], url
        if strategy == "fixture":
            return await super().product_details(
                url=normalized,
                strategy=strategy,
                fixture_html=fixture_html,
            )

        api_warnings: list[str] = []
        product_id = _product_id(normalized)
        if product_id:
            api_product, api_warnings = await self._details_with_public_api(product_id)
            if api_product is not None:
                return api_product, api_warnings, normalized

        product, warnings, source_url = await super().product_details(
            url=normalized,
            strategy=strategy,
            fixture_html=fixture_html,
        )
        return product, sorted(set((api_warnings if product_id else []) + warnings)), source_url

    async def _search_with_public_api(self, query: str) -> tuple[list[ProductResult], list[str]]:
        url = _search_api_url(query)
        payload = await self._fetch_wildberries_api(url)
        if not payload:
            return [], ["WILDBERRIES_API_FAILED"]
        products = [_api_product_to_result(item, query=query, source="wildberries_api_search") for item in _api_products(payload)]
        products = [product for product in products if product is not None]
        if not products:
            return [], ["WILDBERRIES_API_NO_RESULTS"]
        return products, ["WILDBERRIES_API_SEARCH"]

    async def _details_with_public_api(self, product_id: str) -> tuple[ProductResult | None, list[str]]:
        url = _details_api_url(product_id)
        payload = await self._fetch_wildberries_api(url)
        if not payload:
            return None, ["WILDBERRIES_API_FAILED"]
        for item in _api_products(payload):
            if str(item.get("id") or "") == product_id:
                product = _api_product_to_result(item, source="wildberries_api_details")
                if product is not None:
                    return product, ["WILDBERRIES_API_DETAILS"]
        return None, ["WILDBERRIES_API_NO_RESULTS"]

    async def _fetch_wildberries_api(self, url: str) -> dict[str, Any] | None:
        async with httpx.AsyncClient(
            headers=self._wildberries_api_headers(),
            timeout=self.settings.request_timeout,
            follow_redirects=True,
            proxy=self._proxy_url(),
        ) as client:
            response = await client.get(url)
            if response.status_code >= 400:
                return None
            try:
                payload = response.json()
            except ValueError:
                return None
            return payload if isinstance(payload, dict) else None

    def _wildberries_api_headers(self) -> dict[str, str]:
        return {
            # WB's public JSON search endpoint currently rate-limits the repo default
            # Linux/Chrome UA, while the same low-volume read-only requests work with
            # the shorter UA observed to be accepted by the endpoint.
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            "Referer": "https://www.wildberries.ru/",
        }

    def parse_search_results(self, html: str, query: str) -> list[ProductResult]:
        soup = BeautifulSoup(html, "html.parser")
        offers: list[ProductResult] = []
        seen: set[str] = set()
        for link in soup.select("a[href*='/catalog/'][href*='/detail.aspx']"):
            raw_url = str(link.get("href") or "")
            url = self.normalize_product_url(urljoin("https://www.wildberries.ru", raw_url))
            if not self.is_product_url(url) or url in seen:
                continue
            card = link.find_parent(["article", "li", "div"], class_=re.compile(r"product-card|product-card__wrapper"))
            card = card or link.parent or link
            title = (
                link.get("aria-label")
                or link.get("title")
                or _select_text(card, [".product-card__name", ".goods-name", "h2", "h3"])
                or link.get_text(" ", strip=True)
            )
            title = re.sub(r"\s+", " ", str(title)).strip()
            if not title:
                continue
            text = card.get_text(" ", strip=True)
            price = _extract_price(text)
            image = _first_attr(card, ["img"], "src") or _first_attr(card, ["img"], "data-src")
            seen.add(url)
            offers.append(
                ProductResult(
                    marketplace=self.marketplace,
                    title=title,
                    url=url,
                    price=price,
                    currency="RUB",
                    image_url=image,
                    availability="available" if re.search(r"\b(?:В корзину|Купить)\b", text, re.I) else None,
                    confidence=0.9 if price is not None else 0.7,
                    raw={"search_query": query, "card_text": text[:2000]},
                )
            )
        return offers

    def parse_product_details(self, html: str, url: str) -> ProductResult | None:
        soup = BeautifulSoup(html, "html.parser")
        title = _select_text(soup, ["h1", ".product-page__title", ".product-page__header"])
        if not title:
            meta = soup.select_one("meta[property='og:title']")
            title = str(meta.get("content") or "").strip() if meta else ""
        if not title:
            return None
        body = soup.get_text(" ", strip=True)
        image = None
        image_meta = soup.select_one("meta[property='og:image']")
        if image_meta:
            image = image_meta.get("content")
        price = _extract_price(body)
        return ProductResult(
            marketplace=self.marketplace,
            title=title,
            url=self.normalize_product_url(url),
            price=price,
            currency="RUB",
            image_url=image if isinstance(image, str) else None,
            availability="available" if re.search(r"\b(?:В корзину|Купить)\b", body, re.I) else None,
            confidence=0.9 if price is not None else 0.65,
            raw={"source": "rendered_product_page"},
        )


def _search_api_url(query: str) -> str:
    return (
        "https://search.wb.ru/exactmatch/ru/common/v9/search"
        "?ab_testing=false&appType=1&curr=rub&dest=-1257786&page=1"
        f"&query={quote_plus(query)}"
        "&resultset=catalog&sort=popular&spp=30&suppressSpellcheck=false"
    )


def _details_api_url(product_id: str) -> str:
    return f"https://card.wb.ru/cards/v4/detail?appType=1&curr=rub&dest=-1257786&nm={product_id}&spp=30"


def _product_id(url: str) -> str | None:
    match = re.search(r"/catalog/(\d+)/detail\.aspx$", url)
    return match.group(1) if match else None


def _api_products(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_products = payload.get("products")
    if raw_products is None and isinstance(payload.get("data"), dict):
        raw_products = payload["data"].get("products")
    if not isinstance(raw_products, list):
        return []
    return [item for item in raw_products if isinstance(item, dict)]


def _api_product_to_result(
    item: dict[str, Any],
    query: str | None = None,
    source: str = "wildberries_api",
) -> ProductResult | None:
    product_id = str(item.get("id") or "").strip()
    title = re.sub(r"\s+", " ", str(item.get("name") or "")).strip()
    if not product_id or not title:
        return None
    price, old_price = _api_prices(item)
    total_quantity = _as_int(item.get("totalQuantity"))
    raw: dict[str, Any] = {"source": source, "product_id": product_id}
    if query is not None:
        raw["search_query"] = query
    return ProductResult(
        marketplace="wildberries",
        title=title,
        url=f"https://www.wildberries.ru/catalog/{product_id}/detail.aspx",
        price=price,
        old_price=old_price,
        currency="RUB",
        rating=_as_float(item.get("reviewRating") or item.get("rating")),
        reviews_count=_as_int(item.get("feedbacks") or item.get("nmFeedbacks")),
        availability="available" if total_quantity is None or total_quantity > 0 else "out_of_stock",
        seller=str(item.get("brand") or "").strip() or None,
        confidence=0.95 if price is not None else 0.8,
        raw=raw,
    )


def _api_prices(item: dict[str, Any]) -> tuple[float | None, float | None]:
    for size in item.get("sizes") or []:
        if not isinstance(size, dict):
            continue
        price = size.get("price")
        if not isinstance(price, dict):
            continue
        current = _kopecks_to_rub(price.get("product") or price.get("sale") or price.get("total"))
        old = _kopecks_to_rub(price.get("basic"))
        if current is not None:
            return current, old if old and old > current else None
    current = _kopecks_to_rub(item.get("salePriceU") or item.get("salePrice"))
    old = _kopecks_to_rub(item.get("priceU") or item.get("price"))
    return current, old if old and current and old > current else None


def _kopecks_to_rub(value: object) -> float | None:
    parsed = _as_float(value)
    if parsed is None:
        return None
    return parsed / 100.0


def _as_float(value: object) -> float | None:
    if not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _as_int(value: object) -> int | None:
    if not isinstance(value, (int, float, str)):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _select_text(node, selectors: list[str]) -> str:
    for selector in selectors:
        found = node.select_one(selector)
        if found:
            text = (found.get("aria-label") or found.get_text(" ", strip=True) or "").strip()
            if text:
                return text
    return ""


def _first_attr(node, selectors: list[str], attr: str) -> str | None:
    for selector in selectors:
        found = node.select_one(selector)
        if found and found.has_attr(attr):
            value = found.get(attr)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _extract_price(text: str) -> float | None:
    patterns = (
        r"(?:Цена с WB Кошельком|Цена)\s*([0-9][\d\s.,]*)\s*₽",
        r"([0-9][\d\s.,]*)\s*₽",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = parse_price(match.group(1))
            if value is not None:
                return value
    return None
