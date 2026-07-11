from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

from marketplaces_mcp.core.config import Settings, get_settings
from marketplaces_mcp.core.models import ProductResult
from marketplaces_mcp.core.normalize import parse_price


_BLOCKED_MARKERS = (
    "captcha",
    "robot",
    "you are human",
    "подтвердите что вы человек",
    "check you are not a robot",
)


class BaseAdapter(ABC):
    marketplace: str = "generic"
    search_url_template: str = ""
    details_url_template: str = ""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    async def search(
        self,
        query: str,
        limit: int = 10,
        strategy: str = "auto",
        fixture_html: str | None = None,
    ) -> tuple[list[ProductResult], list[str], str]:
        search_url = self.build_search_url(query)
        html, warnings = await self._load_html(query, search_url, strategy=strategy, fixture_html=fixture_html)
        if not html:
            return [], warnings, search_url
        if self._is_blocked(html):
            if "CAPTCHA_OR_BLOCKED" not in warnings:
                warnings.append("CAPTCHA_OR_BLOCKED")
            return [], warnings, search_url
        offers = self.parse_search_results(html, query=query)
        if not offers:
            warnings.append("NO_RESULTS")
            return [], warnings, search_url
        return offers[:limit], warnings, search_url

    async def product_details(
        self,
        url: str,
        strategy: str = "auto",
        fixture_html: str | None = None,
    ) -> tuple[ProductResult | None, list[str], str]:
        html, warnings = await self._load_html(
            query=url,
            url=url,
            strategy=strategy,
            fixture_html=fixture_html,
        )
        if not html:
            return None, warnings, url
        if self._is_blocked(html):
            if "CAPTCHA_OR_BLOCKED" not in warnings:
                warnings.append("CAPTCHA_OR_BLOCKED")
            return None, warnings, url
        product = self.parse_product_details(html, url=url)
        if product is None:
            warnings.append("NO_RESULTS")
        return product, warnings, url

    async def _load_html(
        self,
        query: str,
        url: str,
        strategy: str = "auto",
        fixture_html: str | None = None,
    ) -> tuple[str | None, list[str]]:
        warnings: list[str] = []

        if strategy == "fixture":
            if fixture_html is not None:
                return fixture_html, warnings
            fixture = self._read_fixture(query)
            if fixture is not None:
                return fixture, warnings
            warnings.append("FIXTURE_NOT_FOUND")
            return None, warnings

        try:
            html = await self._fetch_with_playwright(url)
            if html:
                return html, warnings
        except Exception:
            warnings.append("PLAYWRIGHT_FAILED")
        html = await self._fetch_with_http(url)
        if html:
            return html, warnings
        warnings.append("NO_FETCH")
        return None, warnings

    async def _fetch_with_http(self, url: str) -> str | None:
        headers = {
            "User-Agent": self.settings.user_agent,
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        }
        async with httpx.AsyncClient(
            headers=headers,
            timeout=self.settings.request_timeout,
            follow_redirects=True,
        ) as client:
            response = await client.get(url)
            if response.status_code >= 400:
                return None
            return response.text

    async def _fetch_with_playwright(self, url: str) -> str | None:
        try:
            from playwright.async_api import async_playwright
        except Exception:
            return None

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=self.settings.user_agent,
                java_script_enabled=True,
            )
            page = await context.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=120000)
                await page.wait_for_timeout(800)
                return await page.content()
            finally:
                await context.close()
                await browser.close()

    def build_search_url(self, query: str) -> str:
        return self.search_url_template.format(query=quote_plus(query))

    def parse_search_results(self, html: str, query: str) -> list[ProductResult]:
        raise NotImplementedError

    def parse_product_details(self, html: str, url: str) -> ProductResult | None:
        cards = self.parse_search_results(html, query="")
        if cards:
            product = cards[0]
            product.url = url
            return product
        return None

    def _is_blocked(self, html: str) -> bool:
        lowered = html.lower()
        return any(token in lowered for token in _BLOCKED_MARKERS)

    def _read_fixture(self, query: str) -> str | None:
        fixture_dir = Path(os.getenv("MARKETPLACES_FIXTURES_DIR") or self.settings.fixture_dir)
        fixture_path = fixture_dir / self.marketplace / f"{_slugify_query(query)}.html"
        if not fixture_path.exists():
            return None
        return fixture_path.read_text(encoding="utf-8")

    @staticmethod
    def parse_jsonld_offers(html: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        data = []
        for tag in soup.find_all("script", type="application/ld+json"):
            raw = tag.get_text(strip=True)
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except Exception:
                continue
            data.extend(_extract_offers(payload))
        return data


def _slugify_query(query: str) -> str:
    normalized = re.sub(r"\s+", "_", str(query).strip().lower())
    normalized = re.sub(r"[^0-9а-яА-Яa-zA-ZёЁ_-]", "", normalized)
    return normalized or "default"


def _extract_offers(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, (dict, list)):
        return []
    if isinstance(payload, list):
        out: list[dict[str, Any]] = []
        for item in payload:
            out.extend(_extract_offers(item))
        return out

    offers: list[dict[str, Any]] = []
    if payload.get("@type") == "ListItem" and isinstance(payload.get("item"), dict):
        return _extract_offers(payload.get("item", {}))

    if payload.get("@type") in {"Product", "Offer"}:
        name = payload.get("name") or payload.get("title")
        offer = payload.get("offers", {})
        if isinstance(offer, list):
            if offer:
                offer = offer[0]
        if isinstance(offer, dict):
            candidate = {
                "title": name,
                "price": offer.get("price") or offer.get("priceSpecification", {}).get("price"),
                "url": offer.get("url") or payload.get("url"),
                "image_url": payload.get("image"),
                "currency": offer.get("priceCurrency"),
                "rating": payload.get("aggregateRating", {}).get("ratingValue"),
                "reviews_count": payload.get("aggregateRating", {}).get("reviewCount"),
            }
            offers.append(candidate)
        elif name:
            offers.append(
                {
                    "title": name,
                    "price": payload.get("offers", {}).get("lowPrice"),
                    "url": payload.get("url"),
                    "image_url": payload.get("image"),
                    "currency": payload.get("offers", {}).get("priceCurrency"),
                }
            )
    if "itemListElement" in payload and isinstance(payload["itemListElement"], list):
        for element in payload["itemListElement"]:
            if isinstance(element, dict):
                if element.get("@type") == "ListItem":
                    offers.extend(_extract_offers(element.get("item", {})))
                else:
                    offers.extend(_extract_offers(element))
    return offers
