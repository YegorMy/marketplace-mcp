from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from marketplaces_mcp.adapters.base import BaseAdapter
from marketplaces_mcp.core.models import ProductResult
from marketplaces_mcp.core.normalize import parse_price


class OzonAdapter(BaseAdapter):
    marketplace = "ozon"
    search_url_template = "https://www.ozon.ru/search/?text={query}"

    def parse_search_results(self, html: str, query: str) -> list[ProductResult]:
        soup = BeautifulSoup(html, "html.parser")
        offers: list[ProductResult] = []
        cards = soup.select(
            "article, div.tile-root, div[data-widget='searchResultsV2'], .search-result__item"
        )

        if not cards:
            cards = [soup]

        for card in cards:
            title = _select_text(
                card,
                [
                    "a[href][title]",
                    "a.tile-hover-card__title",
                    "h3",
                    "[data-widget='searchResultsV2'] [title]",
                ],
            )
            if not title:
                continue

            url = _first_attr(
                card,
                [
                    "a[href][title]",
                    "a.tile-hover-card__title",
                    "a",
                ],
                "href",
            ) or ""
            if url:
                url = urljoin("https://www.ozon.ru", url)

            price = _select_price(card)
            rating = _select_float(card, ["span[title*='рейтинг']", ".tile-hover-card__rating"])
            reviews = _select_int(card, [".tile-hover-card__reviews", ".ratings-count"])
            image = _first_attr(card, ["img"], "src")
            raw = {
                "raw_title": title,
                "search_query": query,
            }

            offers.append(
                ProductResult(
                    marketplace=self.marketplace,
                    title=title,
                    url=url,
                    price=price,
                    old_price=_select_price(card, selectors=[".old", ".old-price", ".discount-price"]),
                    currency="RUB",
                    rating=rating,
                    reviews_count=reviews,
                    image_url=image,
                    availability=_select_text(card, [".tile-hover-card__availability", ".availability"]),
                    delivery_hint=_select_text(card, [".tile-hover-card__delivery", ".shipping"]),
                    raw=raw,
                )
            )

        if not offers:
            for item in self.parse_jsonld_offers(html):
                title = item.get("title") or item.get("name")
                if not title:
                    continue
                price = parse_price(item.get("price"))
                offers.append(
                    ProductResult(
                        marketplace=self.marketplace,
                        title=str(title),
                        url=item.get("url") or "",
                        price=price,
                        currency=item.get("currency") or "RUB",
                        rating=_as_float(item.get("rating")),
                        reviews_count=_as_int(item.get("reviews_count")),
                        image_url=item.get("image_url"),
                    )
                )
        return offers


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


def _select_price(node, selectors: list[str] | None = None) -> float | None:
    explicit_selectors = selectors is not None
    selectors = selectors or [
        ".tile-hover-card__price",
        ".price",
        ".ts-caption-2",
        "[data-item-price]",
        "span",
    ]
    for selector in selectors:
        found = node.select_one(selector)
        if found:
            text = found.get_text(" ", strip=True)
            parsed = parse_price(text)
            if parsed is not None:
                return parsed
    if explicit_selectors:
        return None
    fallback = node.get_text(" ", strip=True)
    return parse_price(re.search(r"\d[\d\s.,]*\d\s*[₽rubRUBrub.]*", fallback).group(0) if re.search(r"\d[\d\s.,]*\d", fallback) else "")


def _select_float(node, selectors: list[str]) -> float | None:
    text = _select_text(node, selectors)
    return parse_float(text) if text else None


def _select_int(node, selectors: list[str]) -> int | None:
    text = _select_text(node, selectors)
    return parse_int(text) if text else None


def parse_float(value: object) -> float | None:
    if value is None:
        return None
    return parse_price(str(value))


def parse_int(value: object) -> int | None:
    parsed = parse_price(value)
    return int(parsed) if parsed is not None else None


def _as_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return parse_price(value)


def _as_int(value: object) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        parsed = parse_price(value)
        return int(parsed) if parsed is not None else None
