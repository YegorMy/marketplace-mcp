from __future__ import annotations

import json
import os
import re
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlsplit, urlunsplit

import anyio
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
    "похоже, нет соединения",
    "выключите vpn",
    "инцидент:",
    "not a bot",
    "slide the slider",
    "проверяем браузер",
    "доступ ограничен",
    "проблема с ip",
    "для решения капчи",
    "отключить vpn",
)


def accessibility_evidence_excerpt(text: str, max_chars: int = 10000) -> str:
    """Keep the product header plus useful description/specification sections.

    Accessibility snapshots can be tens of thousands of characters because of
    recommendation carousels.  Product research needs the primary offer and
    its material/specification evidence, not the entire page.
    """
    lines = text.splitlines()
    selected: list[str] = []
    selected_indexes: set[int] = set()

    title_index = next(
        (index for index, line in enumerate(lines) if re.search(r'heading ".+" \[level=1\]', line)),
        0,
    )
    ranges = [(title_index, min(len(lines), title_index + 70))]
    section_pattern = re.compile(
        r'heading "(?:Описание|О товаре|Характеристики|Состав|Комплектация)"',
        flags=re.IGNORECASE,
    )
    for index, line in enumerate(lines):
        if section_pattern.search(line):
            ranges.append((index, min(len(lines), index + 90)))

    for start, end in ranges:
        for index in range(start, end):
            if index not in selected_indexes:
                selected_indexes.add(index)
                line = lines[index]
                if re.match(r"^\s*- /url:", line):
                    continue
                selected.append(line[:1000])
    excerpt = "\n".join(selected).strip()
    return excerpt[:max_chars]


class BaseAdapter(ABC):
    marketplace: str = "generic"
    search_url_template: str = ""
    details_url_template: str = ""
    discovery_domain: str = ""
    product_url_patterns: tuple[str, ...] = ()
    camofox_wait_seconds: float = 1.5

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
            if strategy == "fixture":
                return [], sorted(set(warnings)), search_url
            recovered, recovery_warnings = await self._search_with_camofox(search_url, query)
            if recovered:
                return recovered[:limit], sorted(set(warnings + recovery_warnings)), search_url
            offers, discovery_warnings = await self._discover_indexed(query, limit)
            return offers, sorted(set(warnings + recovery_warnings + discovery_warnings)), search_url
        if self._is_blocked(html):
            warnings.append("HIVE_WEB_BLOCKED")
            if strategy == "fixture":
                warnings.append("CAPTCHA_OR_BLOCKED")
                return [], sorted(set(warnings)), search_url
            recovered, recovery_warnings = await self._search_with_camofox(search_url, query)
            if recovered:
                return recovered[:limit], sorted(set(warnings + recovery_warnings)), search_url
            offers, discovery_warnings = await self._discover_indexed(query, limit)
            warnings.append("CAPTCHA_OR_BLOCKED")
            return offers, sorted(set(warnings + recovery_warnings + discovery_warnings)), search_url
        offers = self.parse_search_results(html, query=query)
        if not offers:
            if strategy == "fixture":
                warnings.append("NO_RESULTS")
                return [], sorted(set(warnings)), search_url
            recovered, recovery_warnings = await self._search_with_camofox(search_url, query)
            if recovered:
                return recovered[:limit], sorted(set(warnings + recovery_warnings)), search_url
            discovered, discovery_warnings = await self._discover_indexed(query, limit)
            if discovered:
                return discovered, sorted(set(warnings + recovery_warnings + discovery_warnings)), search_url
            warnings.extend(recovery_warnings + discovery_warnings)
            warnings.append("NO_RESULTS")
            return [], sorted(set(warnings)), search_url
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
            if strategy == "fixture":
                return None, sorted(set(warnings)), url
            recovered, recovery_warnings = await self._details_with_camofox(url)
            return recovered, sorted(set(warnings + recovery_warnings)), url
        if self._is_blocked(html):
            warnings.append("HIVE_WEB_BLOCKED")
            if strategy == "fixture":
                warnings.append("CAPTCHA_OR_BLOCKED")
                return None, sorted(set(warnings)), url
            recovered, recovery_warnings = await self._details_with_camofox(url)
            if recovered is not None:
                return recovered, sorted(set(warnings + recovery_warnings)), url
            warnings.extend(recovery_warnings + ["CAPTCHA_OR_BLOCKED"])
            return None, sorted(set(warnings)), url
        product = self.parse_product_details(html, url=url)
        if product is None:
            if strategy == "fixture":
                warnings.append("NO_RESULTS")
                return None, sorted(set(warnings)), url
            recovered, recovery_warnings = await self._details_with_camofox(url)
            if recovered is not None:
                return recovered, sorted(set(warnings + recovery_warnings)), url
            warnings.extend(recovery_warnings + ["NO_RESULTS"])
        return product, sorted(set(warnings)), url

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

        if self.settings.web_backend in {"hive_web", "auto"}:
            try:
                html = await self._fetch_with_hive_web(url)
                if html:
                    return html, warnings
            except Exception:
                warnings.append("HIVE_WEB_FAILED")
                if self.settings.web_backend == "hive_web":
                    return None, warnings
            else:
                warnings.append("HIVE_WEB_FAILED")
                if self.settings.web_backend == "hive_web":
                    return None, warnings

        if self.settings.web_backend in {"auto", "legacy"}:
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

    async def _fetch_with_hive_web(self, url: str) -> str | None:
        from hive_web_runtime.action_web.browser import ActionWebRuntime

        runtime = ActionWebRuntime()
        session_id: str | None = None
        try:
            session = await runtime.session_create(headless=True)
            session_id = session.session_id
            await runtime.navigate(session_id, url=url)
            # Marketplace parsers need hrefs and card boundaries. Hive's public
            # compact snapshot intentionally returns visible text only, so read
            # the rendered DOM from the same read-only Playwright page.
            page = runtime._get(session_id).page
            await page.wait_for_timeout(800)
            return await page.content()
        finally:
            if session_id is not None:
                await runtime.close(session_id)
            await runtime.shutdown()

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

    async def _fetch_with_camofox(self, url: str) -> str | None:
        if not self.settings.camofox_url:
            return None
        user_id = f"marketplaces-public-{uuid.uuid4().hex[:12]}"
        tab_id: str | None = None
        timeout = httpx.Timeout(max(self.settings.request_timeout, 90.0))
        async with httpx.AsyncClient(base_url=self.settings.camofox_url, timeout=timeout) as client:
            try:
                created = await client.post(
                    "/tabs",
                    json={"userId": user_id, "sessionKey": "readonly", "url": url},
                )
                created.raise_for_status()
                tab_id = str(created.json().get("tabId") or "")
                if not tab_id:
                    return None
                # Tab creation returns before some client-rendered product pages
                # have populated their accessibility tree.
                await anyio.sleep(self.camofox_wait_seconds)
                response = await client.get(f"/tabs/{tab_id}/snapshot", params={"userId": user_id})
                response.raise_for_status()
                return str(response.json().get("snapshot") or "") or None
            finally:
                try:
                    await client.delete(f"/sessions/{user_id}")
                except Exception:
                    pass

    async def _search_with_camofox(
        self,
        url: str,
        query: str,
    ) -> tuple[list[ProductResult], list[str]]:
        try:
            snapshot = await self._fetch_with_camofox(url)
        except Exception:
            return [], ["CAMOFOX_FAILED"]
        if not snapshot:
            return [], ["CAMOFOX_FAILED"]
        if self._is_blocked(snapshot):
            return [], ["CAMOFOX_BLOCKED"]
        products = self.parse_search_results(snapshot, query=query)
        if products:
            return products, ["CAMOFOX_FALLBACK"]
        return [], ["CAMOFOX_NO_RESULTS"]

    async def _details_with_camofox(
        self,
        url: str,
    ) -> tuple[ProductResult | None, list[str]]:
        last_warning = "CAMOFOX_FAILED"
        for attempt in range(2):
            try:
                snapshot = await self._fetch_with_camofox(url)
            except Exception:
                snapshot = None
            if not snapshot:
                last_warning = "CAMOFOX_FAILED"
            elif self._is_blocked(snapshot):
                last_warning = "CAMOFOX_BLOCKED"
            else:
                product = self.parse_product_details(snapshot, url=url)
                if product is not None:
                    warnings = ["CAMOFOX_FALLBACK"]
                    if attempt:
                        warnings.append("CAMOFOX_RETRIED")
                    return product, warnings
                last_warning = "CAMOFOX_NO_RESULTS"
            if attempt == 0:
                await anyio.sleep(0.5)
        return None, [last_warning, "CAMOFOX_RETRIED"]

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

    async def _discover_indexed(
        self,
        query: str,
        limit: int,
    ) -> tuple[list[ProductResult], list[str]]:
        """Return product links from a public search index when a shop blocks.

        Indexed hits are deliberately price-less and low confidence: snippets
        can be stale, but a canonical product URL is still useful to an agent.
        This is discovery, not a bypass of the marketplace anti-bot page.
        """
        if not self.discovery_domain or not self.product_url_patterns:
            return [], []
        try:
            from ddgs import DDGS
        except ImportError:
            return [], ["INDEX_DISCOVERY_UNAVAILABLE"]

        def run_search() -> list[dict[str, Any]]:
            with DDGS(timeout=min(self.settings.request_timeout, 15.0)) as client:
                return list(
                    client.text(
                        f"site:{self.discovery_domain} {query}",
                        region="ru-ru",
                        safesearch="moderate",
                        max_results=max(limit * 3, 8),
                    )
                )

        try:
            hits = await anyio.to_thread.run_sync(run_search)
        except Exception:
            return [], ["INDEX_DISCOVERY_FAILED"]

        products: list[ProductResult] = []
        seen: set[str] = set()
        for hit in hits:
            raw_url = str(hit.get("href") or hit.get("url") or "").strip()
            url = self.normalize_product_url(raw_url)
            if not url or url in seen or not self.is_product_url(url):
                continue
            title = re.sub(r"\s+", " ", str(hit.get("title") or "")).strip()
            if not title:
                continue
            seen.add(url)
            products.append(
                ProductResult(
                    marketplace=self.marketplace,
                    title=title,
                    url=url,
                    currency="RUB",
                    confidence=0.35,
                    raw={
                        "discovery": "public_search_index",
                        "snippet": str(hit.get("body") or "")[:1000],
                        "search_query": query,
                    },
                )
            )
            if len(products) >= limit:
                break
        if products:
            return products, ["INDEX_DISCOVERY_ONLY", "PRICE_UNVERIFIED"]
        return [], ["INDEX_DISCOVERY_NO_RESULTS"]

    def normalize_product_url(self, url: str) -> str:
        if not url:
            return ""
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return ""
        return urlunsplit(("https", parsed.netloc.lower(), parsed.path, "", ""))

    def is_product_url(self, url: str) -> bool:
        return any(re.search(pattern, url, flags=re.IGNORECASE) for pattern in self.product_url_patterns)

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
        # Rendered marketplace HTML contains minified JS bundles with words like
        # "captcha" even on a healthy page. Inspect user-visible text and title,
        # never script/style source, to avoid a false CAPTCHA classification.
        soup = BeautifulSoup(html, "html.parser")
        for node in soup(["script", "style", "noscript"]):
            node.decompose()
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        lowered = f"{title} {soup.get_text(' ', strip=True)}".lower()
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
