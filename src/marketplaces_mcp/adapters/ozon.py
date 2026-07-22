from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from marketplaces_mcp.adapters.base import BaseAdapter, accessibility_evidence_excerpt
from marketplaces_mcp.core.models import ProductResult
from marketplaces_mcp.core.normalize import parse_price


class OzonAdapter(BaseAdapter):
    marketplace = "ozon"
    search_url_template = "https://www.ozon.ru/search/?text={query}"
    discovery_domain = "ozon.ru/product"
    product_url_patterns = (r"https://(?:www\.)?ozon\.ru/product/[^/?#]+(?:-\d+)?/?$",)

    def parse_search_results(self, html: str, query: str) -> list[ProductResult]:
        if "/product/" in html and re.search(r"^\s*- (?:link|text|banner|complementary)", html, re.MULTILINE):
            return _parse_accessibility_search(self, html, query)
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
                url = self.normalize_product_url(url)
            if not self.is_product_url(url):
                continue

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

    def parse_product_details(self, html: str, url: str) -> ProductResult | None:
        if re.search(r"^\s*- (?:heading|banner|text|link)", html, re.MULTILINE):
            title_match = re.search(r'^\s*- heading "([^"]+)" \[level=1\]', html, re.MULTILINE)
            title = title_match.group(1).strip() if title_match else ""
            if title:
                primary_offer = html[title_match.end() : title_match.end() + 6000] if title_match else html
                return ProductResult(
                    marketplace=self.marketplace,
                    title=title,
                    url=self.normalize_product_url(url),
                    price=_extract_current_price(primary_offer),
                    currency="RUB",
                    availability="available" if re.search(r"\b(?:В корзину|Купить)\b", html, re.I) else None,
                    confidence=0.9,
                    raw={
                        "source": "camofox_accessibility_snapshot",
                        "evidence_excerpt": accessibility_evidence_excerpt(html),
                    },
                )
        soup = BeautifulSoup(html, "html.parser")
        title = _select_text(soup, ["h1", "meta[property='og:title']"])
        if not title:
            meta = soup.select_one("meta[property='og:title']")
            title = str(meta.get("content") or "").strip() if meta else ""
        if not title:
            return None
        body = soup.get_text(" ", strip=True)
        price = _extract_current_price(body)
        image = None
        image_meta = soup.select_one("meta[property='og:image']")
        if image_meta:
            image = image_meta.get("content")
        return ProductResult(
            marketplace=self.marketplace,
            title=title,
            url=self.normalize_product_url(url),
            price=price,
            currency="RUB",
            image_url=image if isinstance(image, str) else None,
            availability="available" if re.search(r"\b(?:В корзину|Купить)\b", body, re.I) else None,
            confidence=0.9 if price is not None else 0.65,
            raw={"source": "rendered_product_page", "evidence_excerpt": body[:10000]},
        )


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


def _extract_current_price(text: str) -> float | None:
    patterns = (
        r'(?:button|text):?\s*"?([0-9][\d\s.,]*)\s*₽\s*(?:С банками|С Ozon Картой|с картой Ozon)',
        r"(?:с Ozon Картой|с картой Ozon|Цена)\s*([0-9][\d\s.,]*)\s*₽",
        r"([0-9][\d\s.,]*)\s*₽",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = parse_price(match.group(1))
            if value is not None:
                return value
    return None


def _parse_accessibility_search(adapter: OzonAdapter, text: str, query: str) -> list[ProductResult]:
    link_re = re.compile(
        r'^- link "(?P<title>[^"]+)"(?: \[[^\]]+\])?:\s*\n\s+- /url: (?P<url>/product/[^\s]+)',
        flags=re.MULTILINE,
    )
    ignored = {"распродажа", "цена что надо", "оригинал", "выгодная цена"}
    matches = [m for m in link_re.finditer(text) if m.group("title").strip().lower() not in ignored]
    offers: list[ProductResult] = []
    seen: set[str] = set()
    for index, match in enumerate(matches):
        url = adapter.normalize_product_url(urljoin("https://www.ozon.ru", match.group("url")))
        if not adapter.is_product_url(url) or url in seen:
            continue
        block_end = matches[index + 1].start() if index + 1 < len(matches) else min(len(text), match.end() + 800)
        prefix = text[max(0, match.start() - 300) : match.start()]
        suffix = text[match.end() : block_end]
        price_lines = re.findall(r'^- text: ([^\n]*₽[^\n]*)$', prefix, flags=re.MULTILINE)
        price_values = re.findall(r"([0-9][\d\s]*)\s*₽", price_lines[-1]) if price_lines else []
        price = parse_price(price_values[0]) if price_values else None
        old_price = parse_price(price_values[1]) if len(price_values) > 1 else None
        rating_match = re.search(r'^- text: "?([0-5](?:[.,]\d+)?)"?$', suffix, flags=re.MULTILINE)
        reviews_match = re.search(r"\b([0-9][\d\s]*)\s+отзыв", suffix, flags=re.IGNORECASE)
        stock_match = re.search(r"\b([0-9][\d\s]*)\s+шт\s+осталось", prefix, flags=re.IGNORECASE)
        delivery_match = re.search(r'^- button "([^"]+)"', suffix, flags=re.MULTILINE)
        seen.add(url)
        offers.append(
            ProductResult(
                marketplace=adapter.marketplace,
                title=match.group("title").strip(),
                url=url,
                price=price,
                old_price=old_price,
                currency="RUB",
                rating=parse_price(rating_match.group(1)) if rating_match else None,
                reviews_count=parse_int(reviews_match.group(1)) if reviews_match else None,
                availability=f"{stock_match.group(1).strip()} шт осталось" if stock_match else "available",
                delivery_hint=delivery_match.group(1).strip() if delivery_match else None,
                confidence=0.95 if price is not None else 0.75,
                raw={"source": "camofox_accessibility_snapshot", "search_query": query},
            )
        )
    return offers


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
