from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from marketplaces_mcp.adapters.base import BaseAdapter
from marketplaces_mcp.core.models import ProductResult
from marketplaces_mcp.core.normalize import parse_price


class YandexMarketAdapter(BaseAdapter):
    marketplace = "yandex_market"
    search_url_template = "https://market.yandex.ru/search?text={query}"

    def parse_search_results(self, html: str, query: str) -> list[ProductResult]:
        soup = BeautifulSoup(html, "html.parser")
        offers: list[ProductResult] = []
        cards = soup.select("[data-card-name='snippet'], .n-snippet-card, ._1k4Rr, ._3g9N3")
        if not cards:
            cards = soup.select("article, .card")
        if not cards:
            cards = [soup]

        for card in cards:
            title = _select_text(
                card,
                [
                    "[data-auto='snippet-title']",
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
                    "[data-auto='snippet-title-link']",
                    "a",
                ],
                "href",
            ) or ""
            if url:
                url = urljoin("https://market.yandex.ru", url)

            price = _select_price(card)
            rating = _select_float(card, [".rating", "[data-auto='rating-value']"])
            reviews = _select_int(card, [".rating__count", "[data-auto='feedbacks-count']", ".feedbacks"])
            image = _first_attr(card, ["img", "img[data-tid='f7ec4f6f']"], "src")
            raw = {"raw_title": title, "search_query": query}
            offers.append(
                ProductResult(
                    marketplace=self.marketplace,
                    title=title,
                    url=url,
                    price=price,
                    currency="RUB",
                    rating=rating,
                    reviews_count=reviews,
                    image_url=image,
                    availability=_select_text(
                        card,
                        [
                            "[data-auto='delivery']",
                            "[data-auto='availability']",
                            ".n-snippet-card__link",
                        ],
                    ),
                    delivery_hint=_select_text(
                        card,
                        [
                            "[data-auto='delivery-date']",
                            ".delivery-term",
                        ],
                    ),
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
        if not offers:
            for title, url, price, rating, reviews_count, image_url, delivery_hint, orders_count in _parse_visible_text_cards(
                soup.get_text(" ", strip=True)
            ):
                offers.append(
                    ProductResult(
                        marketplace=self.marketplace,
                        title=title,
                        url=url,
                        price=price,
                        currency="RUB",
                        rating=rating,
                        reviews_count=reviews_count,
                        image_url=image_url,
                        delivery_hint=delivery_hint,
                        raw={"raw_title": title, "search_query": query, "orders_count": orders_count},
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
    selectors = selectors or [
        "[data-auto='snippet-price-current']",
        ".n-product-price",
        ".price",
        "span",
    ]
    for selector in selectors:
        found = node.select_one(selector)
        if found:
            text = found.get_text(" ", strip=True)
            parsed = parse_price(text)
            if parsed is not None:
                return parsed
    fallback = node.get_text(" ", strip=True)
    return parse_price(re.search(r"\d[\d\s.,]*\d", fallback).group(0) if re.search(r"\d[\d\s.,]*\d", fallback) else "")


def _select_float(node, selectors: list[str]) -> float | None:
    text = _select_text(node, selectors)
    return parse_float(text) if text else None


def _select_int(node, selectors: list[str]) -> int | None:
    text = _select_text(node, selectors)
    return parse_int(text) if text else None


def _parse_visible_text_cards(text: str):
    seen: set[tuple[str, float | None]] = set()
    for block in _split_text_blocks(text):
        if not _is_nuphy_air75_block(block):
            continue
        title = _extract_text_card_title(block)
        if not title:
            continue
        price = _extract_text_card_price(block)
        if price is None:
            continue
        rating = _extract_text_card_rating(block)
        reviews_count = _extract_text_card_reviews_count(block)
        delivery_hint = _extract_text_card_delivery_hint(block)
        orders_count = _extract_text_card_orders_count(block)
        if (title, price) in seen:
            continue
        seen.add((title, price))
        yield title, "", price, rating, reviews_count, None, delivery_hint, orders_count


def _split_text_blocks(text: str) -> list[str]:
    chunks = re.split(r"\s+В корзину\b", text, flags=re.IGNORECASE)
    normalized = []
    for chunk in chunks:
        chunk_text = re.sub(r"\s+", " ", chunk).strip()
        if chunk_text:
            normalized.append(chunk_text)
    return normalized


def _is_nuphy_air75_block(text: str) -> bool:
    lowered = text.lower()
    return "nuphy" in lowered and "air75" in lowered and "₽" in text


def _extract_text_card_title(text: str) -> str:
    marker = re.search(r"Цена с картой Яндекс Пэй", text, flags=re.IGNORECASE)
    if marker:
        title = text[:marker.start()].strip(" ,")
    else:
        title = text
    title = _trim_to_product_title_start(title)
    boundaries = [
        "Назначение:",
        "Общее количество",
        "Рейтинг товара:",
        "Оценок:",
        "Цена с картой Яндекс Пэй",
    ]
    lower = title.lower()
    cut = len(title)
    for boundary in boundaries:
        idx = lower.find(boundary.lower())
        if 0 < idx < cut:
            cut = idx
    return title[:cut].strip(" ,")


def _trim_to_product_title_start(text: str) -> str:
    """Remove page chrome/filter text that can precede the first visible product."""
    patterns = (
        r"\bОРИГИНАЛ\s+Клавиатура\b",
        r"\bБеспроводная\s+механическая\s+клавиатура\b",
        r"\bКлавиатура\s+NuPhy\b",
        r"\bNuphy\s+AIR75\b",
        r"\bNuPhy\s+Air75\b",
    )
    starts = [match.start() for pattern in patterns for match in re.finditer(pattern, text, flags=re.IGNORECASE)]
    return text[max(starts) :].strip(" ,") if starts else text


def _extract_text_card_price(text: str) -> float | None:
    match = re.search(r"Цена с картой Яндекс Пэй\s*([0-9][\d\s.,]*)\s*₽", text, flags=re.IGNORECASE)
    if match:
        return parse_price(match.group(0))
    return parse_price(re.search(r"\d[\d\s.,]*\s*₽", text).group(0) if re.search(r"\d[\d\s.,]*\s*₽", text) else "")


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
        r"\b(Сегодня|Завтра|Послезавтра)\b\s*,?\s*(.*?)\s*(?=\s*(?:В корзину|Оценок|Рейтинг товара|·|$))",
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
