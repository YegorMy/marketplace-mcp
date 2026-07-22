from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from marketplaces_mcp.adapters.base import BaseAdapter
from marketplaces_mcp.core.models import ProductResult
from marketplaces_mcp.core.normalize import parse_price


class WildberriesAdapter(BaseAdapter):
    marketplace = "wildberries"
    search_url_template = "https://www.wildberries.ru/catalog/0/search.aspx?search={query}"
    discovery_domain = "wildberries.ru/catalog"
    product_url_patterns = (r"https://(?:www\.)?wildberries\.ru/catalog/\d+/detail\.aspx$",)

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
