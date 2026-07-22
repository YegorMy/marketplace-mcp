from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from marketplaces_mcp.adapters.base import BaseAdapter, accessibility_evidence_excerpt
from marketplaces_mcp.core.models import ProductResult
from marketplaces_mcp.core.normalize import parse_price


class YandexMarketAdapter(BaseAdapter):
    marketplace = "yandex_market"
    search_url_template = "https://market.yandex.ru/search?text={query}&local-offers-first=0"
    discovery_domain = "market.yandex.ru/card"
    product_url_patterns = (r"https://market\.yandex\.ru/(?:card|product--)/[^/?#]+/\d+/?$",)

    async def search(
        self,
        query: str,
        limit: int = 10,
        strategy: str = "auto",
        fixture_html: str | None = None,
    ) -> tuple[list[ProductResult], list[str], str]:
        products, warnings, search_url = await super().search(
            query=query,
            limit=limit,
            strategy=strategy,
            fixture_html=fixture_html,
        )
        if products or strategy == "fixture":
            return products, warnings, search_url
        if not {"HIVE_WEB_BLOCKED", "NO_RESULTS", "CAPTCHA_OR_BLOCKED"}.intersection(warnings):
            return products, warnings, search_url

        try:
            html = await self._fetch_with_http(search_url)
        except Exception:
            return products, sorted(set(warnings + ["YANDEX_HTTP_FALLBACK_FAILED"])), search_url
        if not html:
            return products, sorted(set(warnings + ["YANDEX_HTTP_FALLBACK_FAILED"])), search_url

        http_products = self.parse_search_results(html, query=query)
        if http_products:
            return http_products[:limit], sorted(set(warnings + ["YANDEX_HTTP_FALLBACK"])), search_url
        if self._is_blocked(html):
            return products, sorted(set(warnings + ["YANDEX_HTTP_BLOCKED"])), search_url
        return products, sorted(set(warnings + ["YANDEX_HTTP_NO_RESULTS"])), search_url

    def parse_search_results(self, html: str, query: str) -> list[ProductResult]:
        if "/card/" in html and re.search(r"^- (?:article|link|dialog|banner)", html, re.MULTILINE):
            return _parse_accessibility_search(self, html, query)
        soup = BeautifulSoup(html, "html.parser")
        offers: list[ProductResult] = []
        cards = soup.select("[data-zone-name='productSnippet']")
        if not cards:
            cards = soup.select("[data-card-name='snippet'], .n-snippet-card, ._1k4Rr, ._3g9N3")
        if not cards:
            cards = soup.select("article, .card")
        if not cards:
            cards = [soup]

        for card in cards:
            title = _select_text(
                card,
                [
                    "[data-zone-name='title'] a[href*='/card/']",
                    "[data-auto='snippet-title']",
                    "[data-auto='snippet-link']",
                    "a[href*='/card/']",
                    "h3",
                    "h2",
                    "[data-testid='snippet-title']",
                ],
            )
            if not title:
                continue

            url = _first_attr(
                card,
                [
                    "[data-zone-name='title'] a[href*='/card/']",
                    "[data-auto='snippet-title-link']",
                    "[data-auto='snippet-link']",
                    "a[href*='/card/']",
                ],
                "href",
            ) or ""
            if url:
                url = urljoin("https://market.yandex.ru", url)
                url = self.normalize_product_url(url)
            if not self.is_product_url(url):
                continue

            price = _select_price(card)
            card_text = card.get_text(" ", strip=True)
            rating = _select_float(card, [".rating", "[data-auto='rating-value']"]) or _extract_text_card_rating(card_text)
            reviews = _select_int(card, [".rating__count", "[data-auto='feedbacks-count']", ".feedbacks"])
            if reviews is None:
                reviews = _extract_text_card_reviews_count(card_text)
            image = _first_attr(card, ["img", "img[data-tid='f7ec4f6f']"], "src")
            raw = {"raw_title": title, "search_query": query, "card_text": card_text[:2000]}
            offers.append(
                ProductResult(
                    marketplace=self.marketplace,
                    title=title,
                    url=url,
                    price=price,
                    old_price=_extract_old_price(card_text),
                    currency="RUB",
                    rating=rating,
                    reviews_count=reviews,
                    image_url=image,
                    availability=_extract_availability(card_text),
                    delivery_hint=_extract_text_card_delivery_hint(card_text),
                    confidence=0.95 if price is not None else 0.75,
                    raw=raw,
                )
            )

        if not offers:
            for item in self.parse_jsonld_offers(html):
                title = item.get("title") or item.get("name")
                if not title:
                    continue
                offers.append(
                    ProductResult(
                        marketplace=self.marketplace,
                        title=str(title),
                        url=item.get("url") or "",
                        price=parse_price(item.get("price")),
                        currency=item.get("currency") or "RUB",
                        rating=_as_float(item.get("rating")),
                        reviews_count=_as_int(item.get("reviews_count")),
                        image_url=item.get("image_url"),
                        raw={"jsonld": item},
                    )
                )
        return offers

    def parse_product_details(self, html: str, url: str) -> ProductResult | None:
        if re.search(r"^\s*- (?:heading|dialog|banner|link)", html, re.MULTILINE):
            title_match = re.search(r'^\s*- heading "([^"]+)" \[level=1\]', html, re.MULTILINE)
            title = title_match.group(1).strip() if title_match else ""
            if title:
                primary_offer = html[title_match.end() : title_match.end() + 6000] if title_match else html
                return ProductResult(
                    marketplace=self.marketplace,
                    title=title,
                    url=self.normalize_product_url(url),
                    price=_extract_text_card_price(primary_offer),
                    old_price=_extract_old_price(primary_offer),
                    currency="RUB",
                    rating=_extract_text_card_rating(html),
                    reviews_count=_extract_text_card_reviews_count(html),
                    availability=_extract_availability(html),
                    delivery_hint=_extract_text_card_delivery_hint(html),
                    confidence=0.95,
                    raw={
                        "source": "camofox_accessibility_snapshot",
                        "evidence_excerpt": accessibility_evidence_excerpt(html),
                    },
                )
        soup = BeautifulSoup(html, "html.parser")
        title = _select_text(soup, ["h1", "[data-auto='productCardTitle']"])
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
        price = _extract_text_card_price(body)
        return ProductResult(
            marketplace=self.marketplace,
            title=title,
            url=self.normalize_product_url(url),
            price=price,
            old_price=_extract_old_price(body),
            currency="RUB",
            rating=_extract_text_card_rating(body),
            reviews_count=_extract_text_card_reviews_count(body),
            image_url=image if isinstance(image, str) else None,
            availability=_extract_availability(body),
            delivery_hint=_extract_text_card_delivery_hint(body),
            confidence=0.95 if price is not None else 0.7,
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
    selectors = selectors or [
        "[data-auto='snippet-price-current']",
        ".n-product-price",
        ".price",
    ]
    for selector in selectors:
        found = node.select_one(selector)
        if found:
            text = found.get_text(" ", strip=True)
            parsed = parse_price(text)
            if parsed is not None:
                return parsed
    return _extract_text_card_price(node.get_text(" ", strip=True))


def _select_float(node, selectors: list[str]) -> float | None:
    text = _select_text(node, selectors)
    return parse_float(text) if text else None


def _select_int(node, selectors: list[str]) -> int | None:
    text = _select_text(node, selectors)
    return parse_int(text) if text else None


def _extract_text_card_price(text: str) -> float | None:
    match = re.search(r"Цена с картой Яндекс Пэй\s*([0-9][\d\s.,]*)\s*₽", text, flags=re.IGNORECASE)
    if match:
        return parse_price(match.group(0))
    match = re.search(r'(?:button|text):?\s*"?([0-9][\d\s.,]*)\s*₽(?:\s+Пэй)?', text, flags=re.IGNORECASE)
    if match:
        return parse_price(match.group(1))
    return parse_price(re.search(r"\d[\d\s.,]*\s*₽", text).group(0) if re.search(r"\d[\d\s.,]*\s*₽", text) else "")


def _extract_old_price(text: str) -> float | None:
    match = re.search(r"\bвместо\s*([0-9][\d\s.,]*)\s*₽", text, flags=re.IGNORECASE)
    return parse_price(match.group(1)) if match else None


def _extract_availability(text: str) -> str | None:
    match = re.search(r"\bОсталось\s+\d+\s+шт", text, flags=re.IGNORECASE)
    if match:
        return match.group(0)
    if re.search(r"\bВ корзину\b", text, flags=re.IGNORECASE):
        return "available"
    return None


def _extract_text_card_rating(text: str) -> float | None:
    match = re.search(r"Рейтинг товара:\s*([0-9]+(?:[.,][0-9]+)?)", text, flags=re.IGNORECASE)
    if match:
        return parse_price(match.group(1))
    match = re.search(r"[0-9]+(?:[.,][0-9]+)?\s*\(\s*\d+\s*\)", text)
    if match:
        return parse_price(match.group(0).split("(", 1)[0].strip())
    return None


def _extract_text_card_reviews_count(text: str) -> int | None:
    patterns = (
        r"Оценок:\s*\(\s*(\d+)\s*\)",
        r"[Рр]ейтинг товара:\s*[0-9]+(?:[.,][0-9]+)?\s*\(\s*(\d+)\s*\)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return parse_int(match.group(1))
    return None


def _extract_text_card_orders_count(text: str) -> int | None:
    match = re.search(r"\b(\d+)\s*купили\b", text, flags=re.IGNORECASE)
    return parse_int(match.group(1)) if match else None


def _extract_text_card_delivery_hint(text: str) -> str | None:
    segment = text
    bought_matches = list(re.finditer(r"\b\d+\s*купили\b", segment, flags=re.IGNORECASE))
    if bought_matches:
        segment = segment[bought_matches[-1].end() :]
    else:
        price_match = re.search(r"Цена с картой Яндекс Пэй\s*[0-9][\d\s.,]*\s*₽", segment, flags=re.IGNORECASE)
        if price_match:
            segment = segment[price_match.end() :]
    match = re.search(
        r"\b(Сегодня|Завтра|Послезавтра|До\s+\d+\s+дн(?:я|ей))\b\s*,?\s*(.*?)\s*(?=\s*(?:В корзину|Оценок|Рейтинг товара|·|$))",
        segment,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    day = match.group(1)
    suffix = (match.group(2) or "").strip(" ,")
    if not suffix:
        return day
    lowered = suffix.lower()
    if lowered.startswith("курьер"):
        suffix = "курьер"
    elif lowered.startswith("доставка магазина"):
        suffix = "доставка магазина"
    elif lowered.startswith("доставка"):
        suffix = "доставка"
    hint = ", ".join(part for part in (day, suffix) if part).strip(" ,")
    hint = re.sub(r"\s+[A-Za-zА-Яа-я0-9_-]*\.(?:ру|рф|com|ru)\b.*$", "", hint, flags=re.IGNORECASE)
    return hint.strip(" ,")


def _parse_accessibility_search(
    adapter: YandexMarketAdapter,
    text: str,
    query: str,
) -> list[ProductResult]:
    link_re = re.compile(
        r'^\s*- link "(?P<title>[^"]+)"(?: \[[^\]]+\])?:\s*\n\s+- /url: (?P<url>(?:https://market\.yandex\.ru)?/card/[^\s]+)',
        flags=re.MULTILINE,
    )
    groups: list[dict[str, object]] = []
    for match in link_re.finditer(text):
        raw_title = match.group("title").strip()
        if raw_title.lower().startswith(("цена ", "в корзину", "добавить ")):
            continue
        url = adapter.normalize_product_url(urljoin("https://market.yandex.ru", match.group("url")))
        if not adapter.is_product_url(url):
            continue
        title = re.sub(r"\s+\d+\s*%\s*ПРОМОКОД\s*$", "", raw_title, flags=re.IGNORECASE).strip()
        if not title:
            continue
        if groups and groups[-1]["url"] == url:
            groups[-1]["titles"].append(title)
            continue
        groups.append({"url": url, "titles": [title], "start": match.start()})

    offers: list[ProductResult] = []
    for index, group in enumerate(groups):
        start = int(group["start"])
        end = int(groups[index + 1]["start"]) if index + 1 < len(groups) else min(len(text), start + 2500)
        block = text[start:end]
        titles = [str(item) for item in group["titles"]]
        title = min(titles, key=len)
        price = _extract_text_card_price(block)
        offers.append(
            ProductResult(
                marketplace=adapter.marketplace,
                title=title,
                url=str(group["url"]),
                price=price,
                old_price=_extract_old_price(block),
                currency="RUB",
                rating=_extract_text_card_rating(block),
                reviews_count=_extract_text_card_reviews_count(block),
                availability=_extract_availability(block),
                delivery_hint=_extract_text_card_delivery_hint(block),
                confidence=0.95 if price is not None else 0.75,
                raw={"source": "camofox_accessibility_snapshot", "search_query": query},
            )
        )
    return offers


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
        parsed = parse_price(value)
        return parsed


def _as_int(value: object) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        parsed = parse_price(value)
        return int(parsed) if parsed is not None else None
