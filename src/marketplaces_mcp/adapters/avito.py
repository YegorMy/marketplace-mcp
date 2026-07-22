from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import anyio
from bs4 import BeautifulSoup

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None

from marketplaces_mcp.adapters.base import BaseAdapter
from marketplaces_mcp.core.models import ProductResult
from marketplaces_mcp.core.normalize import parse_price


class AvitoAdapter(BaseAdapter):
    marketplace = "avito"
    search_url_template = "https://www.avito.ru/{region}?q={query}"
    discovery_domain = "avito.ru"
    product_url_patterns = (
        r"https://(?:www\.)?avito\.ru/(?:[^/?#]+/)+[^/?#]+_\d+$",
    )
    camofox_wait_seconds = 4.0

    def build_search_url(self, query: str) -> str:
        from urllib.parse import quote_plus

        return self.search_url_template.format(
            region=self.settings.avito_region_slug,
            query=quote_plus(query),
        )

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
        allowed, wait_seconds = await self._reserve_live_request()
        if not allowed:
            products, warnings = await self._discover_indexed(query, limit)
            return products, sorted(set(warnings + ["AVITO_IP_COOLDOWN"])), search_url
        if wait_seconds:
            await anyio.sleep(wait_seconds)

        snapshot, transport_warnings = await self._fetch_readonly_snapshot(search_url)
        if snapshot and self._is_blocked(snapshot):
            await self._record_ip_block()
            products, discovery_warnings = await self._discover_indexed(query, limit)
            warnings = transport_warnings + discovery_warnings + [
                "AVITO_IP_BLOCKED",
                "CAPTCHA_OR_BLOCKED",
            ]
            return products, sorted(set(warnings)), search_url
        if snapshot:
            products = self.parse_search_results(snapshot, query=query)
            if products:
                return products[:limit], sorted(set(transport_warnings)), search_url

        products, discovery_warnings = await self._discover_indexed(query, limit)
        warnings = transport_warnings + discovery_warnings + ["AVITO_LIVE_NO_RESULTS"]
        return products, sorted(set(warnings)), search_url

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

        allowed, wait_seconds = await self._reserve_live_request()
        if not allowed:
            return None, ["AVITO_IP_COOLDOWN"], normalized
        if wait_seconds:
            await anyio.sleep(wait_seconds)

        snapshot, warnings = await self._fetch_readonly_snapshot(normalized)
        if snapshot and self._is_blocked(snapshot):
            await self._record_ip_block()
            return None, sorted(set(warnings + ["AVITO_IP_BLOCKED", "CAPTCHA_OR_BLOCKED"])), normalized
        if snapshot:
            product = self.parse_product_details(snapshot, normalized)
            if product is not None:
                return product, sorted(set(warnings)), normalized
        return None, sorted(set(warnings + ["AVITO_LIVE_NO_RESULTS"])), normalized

    async def _fetch_readonly_snapshot(self, url: str) -> tuple[str | None, list[str]]:
        try:
            snapshot = await self._fetch_with_camofox(url)
        except Exception:
            snapshot = None
        if snapshot:
            return snapshot, ["CAMOFOX_READONLY"]
        return None, ["CAMOFOX_FAILED"]

    async def _reserve_live_request(self) -> tuple[bool, float]:
        return await anyio.to_thread.run_sync(self._reserve_live_request_sync)

    def _reserve_live_request_sync(self) -> tuple[bool, float]:
        now = time.time()
        with _locked_state(self.settings.avito_state_path) as state:
            blocked_until = _as_float(state.get("blocked_until"))
            if blocked_until > now:
                return False, 0.0
            last_request_at = _as_float(state.get("last_request_at"))
            reserved_at = max(now, last_request_at + self.settings.avito_min_interval_seconds)
            state["last_request_at"] = reserved_at
            return True, max(reserved_at - now, 0.0)

    async def _record_ip_block(self) -> None:
        await anyio.to_thread.run_sync(self._record_ip_block_sync)

    def _record_ip_block_sync(self) -> None:
        now = time.time()
        with _locked_state(self.settings.avito_state_path) as state:
            state["blocked_at"] = now
            state["blocked_until"] = now + self.settings.avito_block_cooldown_seconds

    def parse_search_results(self, html: str, query: str) -> list[ProductResult]:
        offers: list[ProductResult] = []
        seen: set[str] = set()

        for title, raw_url in re.findall(
            r'- link "([^"]+)"[^\n]*:\s*\n\s*- /url: ([^\s]+)',
            html,
        ):
            url = self.normalize_product_url(urljoin("https://www.avito.ru", raw_url))
            if not self.is_product_url(url) or url in seen:
                continue
            seen.add(url)
            offers.append(
                ProductResult(
                    marketplace=self.marketplace,
                    title=_clean(title),
                    url=url,
                    currency="RUB",
                    confidence=0.45,
                    raw={"search_query": query, "source": "rendered_search_link"},
                )
            )

        if offers:
            return offers

        soup = BeautifulSoup(html, "html.parser")
        for link in soup.select("a[href]"):
            raw_url = str(link.get("href") or "")
            url = self.normalize_product_url(urljoin("https://www.avito.ru", raw_url))
            if not self.is_product_url(url) or url in seen:
                continue
            title = _clean(str(link.get("title") or link.get_text(" ", strip=True)))
            if not title:
                continue
            seen.add(url)
            offers.append(
                ProductResult(
                    marketplace=self.marketplace,
                    title=title,
                    url=url,
                    currency="RUB",
                    confidence=0.45,
                    raw={"search_query": query, "source": "rendered_search_link"},
                )
            )
        return offers

    def parse_product_details(self, html: str, url: str) -> ProductResult | None:
        title_match = re.search(r'^- heading "([^"]+)" \[level=1\]$', html, flags=re.MULTILINE)
        if title_match:
            return self._parse_accessibility_details(html, url, title_match)

        soup = BeautifulSoup(html, "html.parser")
        title_node = soup.select_one("h1")
        title = title_node.get_text(" ", strip=True) if title_node else ""
        if not title:
            meta = soup.select_one("meta[property='og:title']")
            title = str(meta.get("content") or "").strip() if meta else ""
        if not title:
            return None

        body = soup.get_text(" ", strip=True)
        removed = "объявление снято с публикации" in body.lower()
        price = None if removed else _first_price(body[:3000])
        return ProductResult(
            marketplace=self.marketplace,
            title=_clean(title),
            url=self.normalize_product_url(url),
            price=price,
            currency="RUB",
            availability="removed" if removed else "available",
            confidence=0.85 if price is not None and not removed else 0.65,
            raw={"source": "rendered_product_page", "evidence_excerpt": body[:10000]},
        )

    def _parse_accessibility_details(
        self,
        text: str,
        url: str,
        title_match: re.Match[str],
    ) -> ProductResult:
        title = _clean(title_match.group(1))
        header = text[title_match.end() : title_match.end() + 700]
        removed = "объявление снято с публикации" in header.lower()
        price = None if removed else _first_price(header)
        condition = _field(text, "Состояние")
        location = _section_value(text, "Местоположение")
        description = _description(text)

        seller = None
        seller_rating = None
        seller_reviews_count = None
        seller_match = re.search(
            r'^- heading "([^"]+)" \[level=3\]\s*\n- text: ([0-5](?:[.,]\d+)?)$',
            text,
            flags=re.MULTILINE,
        )
        if seller_match:
            seller = _clean(seller_match.group(1))
            seller_rating = parse_price(seller_match.group(2))
            seller_block = text[seller_match.end() : seller_match.end() + 1000]
            reviews_match = re.search(r'link "(\d[\d\s]*) отзыв', seller_block)
            if reviews_match:
                seller_reviews_count = _as_int(reviews_match.group(1))

        listing_match = re.search(
            r'№\s*(\d+)\s*·\s*([^·\n]+?)\s*·\s*(\d[\d\s]*)\s+просмотр',
            text,
            flags=re.IGNORECASE,
        )
        listing_id = listing_match.group(1) if listing_match else _listing_id(url)
        published_at = _clean(listing_match.group(2)) if listing_match else None
        views_count = _as_int(listing_match.group(3)) if listing_match else None
        seller_type_match = re.search(r'^- paragraph: (Частное лицо|Компания)$', text, flags=re.MULTILINE)
        delivery_available = bool(re.search(r'Авито Доставк|Купить с доставкой', text, flags=re.IGNORECASE))

        raw_fields = {
            "source": "camofox_accessibility_snapshot",
            "listing_id": listing_id,
            "appearance": _field(text, "Внешний вид"),
            "description": description,
            "evidence_excerpt": _evidence_excerpt(text, title_match.start()),
        }
        return ProductResult(
            marketplace=self.marketplace,
            title=title,
            url=self.normalize_product_url(url),
            price=price,
            currency="RUB",
            availability="removed" if removed else "available",
            delivery_hint="Авито Доставка доступна" if delivery_available else None,
            seller=seller,
            seller_type=seller_type_match.group(1) if seller_type_match else None,
            seller_rating=seller_rating,
            seller_reviews_count=seller_reviews_count,
            condition=condition,
            location=location,
            published_at=published_at,
            views_count=views_count,
            delivery_available=delivery_available,
            confidence=0.93 if price is not None and not removed else 0.7,
            raw=raw_fields,
        )


def _first_price(value: str) -> float | None:
    match = re.search(r"(\d[\d\s]*)\s*₽", value)
    return parse_price(match.group(1)) if match else None


def _field(text: str, label: str) -> str | None:
    match = re.search(rf'["\s]{re.escape(label)}:\s*([^"\n]+)', text, flags=re.IGNORECASE)
    return _clean(match.group(1)) if match else None


def _section_value(text: str, heading: str) -> str | None:
    match = re.search(
        rf'^- heading "{re.escape(heading)}" \[level=2\](.*?)(?=^- (?:heading|article|button)\b|\Z)',
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    if not match:
        return None
    values = re.findall(r'^- paragraph: (.+)$', match.group(1), flags=re.MULTILINE)
    values = [_clean(value) for value in values if _clean(value)]
    return values[-1] if values else None


def _description(text: str) -> str | None:
    match = re.search(
        r'^- heading "Описание" \[level=2\](.*?)(?=^- heading |^- button "Читать полностью"|\Z)',
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    if not match:
        return None
    paragraphs = re.findall(r'^- paragraph: (.+)$', match.group(1), flags=re.MULTILINE)
    cleaned = [_clean(value) for value in paragraphs if _clean(value)]
    return " ".join(cleaned)[:6000] or None


def _evidence_excerpt(text: str, start: int) -> str:
    end_match = re.search(r'^- navigation ', text[start:], flags=re.MULTILINE)
    end = start + end_match.start() if end_match else min(len(text), start + 12000)
    return text[start:end][:12000]


def _listing_id(url: str) -> str | None:
    match = re.search(r"_(\d+)$", url.rstrip("/"))
    return match.group(1) if match else None


def _as_int(value: str) -> int | None:
    digits = re.sub(r"\D", "", value)
    return int(digits) if digits else None


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().strip('"')).strip()


class _locked_state:
    """Small cross-process state transaction shared by both Hermes profiles."""

    def __init__(self, path: Path):
        self.path = path
        self.lock_path = path.with_suffix(path.suffix + ".lock")
        self.lock_file = None
        self.state: dict[str, object] = {}

    def __enter__(self) -> dict[str, object]:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)
        descriptor = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        self.lock_file = os.fdopen(descriptor, "r+")
        _lock_file(self.lock_file)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                self.state = payload
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self.state = {}
        return self.state

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        try:
            if exc_type is None:
                self.path.write_text(json.dumps(self.state, sort_keys=True), encoding="utf-8")
                os.chmod(self.path, 0o600)
        finally:
            if self.lock_file is not None:
                _unlock_file(self.lock_file)
                self.lock_file.close()


def _lock_file(lock_file) -> None:
    if fcntl is not None:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        return
    if msvcrt is not None:  # pragma: no cover - Windows
        lock_file.seek(0)
        if not lock_file.read(1):
            lock_file.write("\0")
            lock_file.flush()
        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)


def _unlock_file(lock_file) -> None:
    if fcntl is not None:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        return
    if msvcrt is not None:  # pragma: no cover - Windows
        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


def _as_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
