from __future__ import annotations

import json
import os
import re
import math
import tempfile
import time
import uuid
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import anyio
import httpx
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
from marketplaces_mcp.core.game_offers import classify_game_offer
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
    camofox_snapshot_attempts = 3
    camofox_reuse_anonymous_session = True

    def _camofox_user_id(self) -> str:
        # Both profiles sharing the access gate also share one anonymous browser
        # context. No login, owner cookies or session export is introduced.
        identity = str(self.settings.avito_state_path.expanduser().resolve())
        return "marketplaces-avito-public-" + hashlib.sha256(identity.encode()).hexdigest()[:16]

    def _camofox_snapshot_pending(self, snapshot: str) -> bool:
        reason = _block_reason(snapshot)
        if reason and reason != "AVITO_BROWSER_CHECK_PENDING":
            return False
        # Wait only for ordinary rendering in this same tab, never solve a challenge.
        return reason == "AVITO_BROWSER_CHECK_PENDING" or not (
            re.search(r'heading ".+" \[level=1\]|/url: [^\s]+_\d+', snapshot)
            or re.search(r"ничего не найдено|объявление снято", snapshot, re.I)
        )

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
        snapshot, transport_warnings = await self._fetch_live_snapshot(search_url)
        if _ACCESS_STOP.intersection(transport_warnings):
            products, warnings = await self._discover_indexed(query, limit)
            return products, sorted(set(warnings + transport_warnings)), search_url
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

        snapshot, warnings = await self._fetch_live_snapshot(normalized)
        if _ACCESS_STOP.intersection(warnings):
            return None, warnings, normalized
        if snapshot:
            product = self.parse_product_details(snapshot, normalized)
            if product is not None:
                return product, sorted(set(warnings)), normalized
        return None, sorted(set(warnings + ["AVITO_LIVE_NO_RESULTS"])), normalized

    async def _fetch_readonly_snapshot(self, url: str) -> tuple[str | None, list[str]]:
        if not self.settings.camofox_url:
            return None, ["CAMOFOX_NOT_CONFIGURED"]
        try:
            snapshot = await self._fetch_with_camofox(url)
        except (TimeoutError, httpx.TimeoutException):
            return None, ["AVITO_TRANSPORT_TIMEOUT"]
        except httpx.HTTPStatusError as exc:
            return None, [f"AVITO_BROWSER_HTTP_{exc.response.status_code}"]
        except Exception:
            return None, ["AVITO_BROWSER_TRANSPORT_FAILED"]
        if snapshot:
            return snapshot, ["CAMOFOX_READONLY"]
        return None, [self._camofox_unavailable_warning()]

    async def access_status(self) -> dict[str, Any]:
        """Read shared access diagnostics without contacting Avito or its index."""
        try:
            return await anyio.to_thread.run_sync(self._access_status_sync)
        except (OSError, ValueError):
            return {"state": "error", "reason": "AVITO_ACCESS_STATE_INVALID",
                    "live_request_allowed": False, "price_verified": False}

    def _access_status_sync(self) -> dict[str, Any]:
        now = time.time()
        with _locked_state(self.settings.avito_state_path, write=False) as state:
            until = _as_float(state.get("blocked_until"))
            inflight = _as_float(state.get("in_flight_until"))
            blocked = until > now
            busy = inflight > now
            next_request = _as_float(state.get("last_request_at")) + self.settings.avito_min_interval_seconds
            rate_wait = next_request > now
            retry = until if blocked else inflight if busy else next_request if rate_wait else now
            return {
                "state": "cooldown" if blocked else "busy" if busy else "rate_wait" if rate_wait else "ready_for_probe",
                "reason": (state.get("blocked_reason", "legacy_unclassified_block") if blocked
                           else "AVITO_REQUEST_IN_PROGRESS" if busy else "AVITO_RATE_LIMIT_WAIT" if rate_wait else None),
                "retry_at": _iso_time(retry) if retry > now else None,
                "retry_after_seconds": max(0, math.ceil(retry - now)),
                "last_blocked_at": _iso_time(_as_float(state.get("blocked_at"))),
                "last_page_read_at": _iso_time(_as_float(state.get("last_page_read_at"))),
                "last_result": state.get("last_result"),
                "live_request_allowed": not blocked and not busy and not rate_wait,
                "price_verified": False,
                "note": "Retry time is a local not-before limit, not proof that Avito has restored access.",
            }

    async def _fetch_live_snapshot(self, url: str) -> tuple[str | None, list[str]]:
        # A cross-process lease covers waiting, navigation and block recording.
        # Other profiles cannot start a queued request after this one sees a block.
        token = uuid.uuid4().hex
        try:
            allowed, wait, warning = await anyio.to_thread.run_sync(self._acquire_live_lease, token)
        except (OSError, ValueError):
            return None, ["AVITO_ACCESS_STATE_INVALID"]
        if not allowed:
            return None, [warning]
        result = "AVITO_TRANSPORT_INTERRUPTED"
        block = None
        try:
            with anyio.fail_after(120):
                if wait:
                    await anyio.sleep(wait)
                warning = await anyio.to_thread.run_sync(self._start_live_lease, token)
                if warning:
                    result = warning
                    return None, [warning]
                snapshot, warnings = await self._fetch_readonly_snapshot(url)
                block = _block_reason(snapshot) if snapshot else None
                if block:
                    result = block
                    return None, sorted(set(warnings + [block, "CAPTCHA_OR_BLOCKED"]))
                result = "PAGE_READ" if snapshot else "AVITO_TRANSPORT_EMPTY"
                return snapshot, warnings
        except TimeoutError:
            result = "AVITO_TRANSPORT_TIMEOUT"
            return None, [result]
        finally:
            # Cancellation must release our lease, without deleting another request's lease.
            with anyio.CancelScope(shield=True):
                await anyio.to_thread.run_sync(self._finish_live_lease, token, result, block)

    def _acquire_live_lease(self, token: str) -> tuple[bool, float, str]:
        now = time.time()
        with _locked_state(self.settings.avito_state_path) as state:
            if _as_float(state.get("blocked_until")) > now:
                return False, 0, _cooldown_warning(state)
            if _as_float(state.get("in_flight_until")) > now:
                return False, 0, "AVITO_REQUEST_IN_PROGRESS"
            wait = max(0, _as_float(state.get("last_request_at")) + self.settings.avito_min_interval_seconds - now)
            if wait > 30:
                return False, 0, "AVITO_RATE_LIMIT_WAIT"
            state["in_flight_token"] = token
            state["in_flight_until"] = now + 180
            return True, wait, ""

    def _start_live_lease(self, token: str) -> str | None:
        with _locked_state(self.settings.avito_state_path) as state:
            if state.get("in_flight_token") != token:
                return "AVITO_REQUEST_IN_PROGRESS"
            if _as_float(state.get("blocked_until")) > time.time():
                return _cooldown_warning(state)
            state["last_request_at"] = time.time()
        return None

    def _finish_live_lease(self, token: str, result: str, block: str | None) -> None:
        now = time.time()
        with _locked_state(self.settings.avito_state_path) as state:
            if state.get("in_flight_token") != token and not block:
                return
            if block:
                state["blocked_at"] = now
                state["blocked_until"] = max(_as_float(state.get("blocked_until")),
                                             now + self.settings.avito_block_cooldown_seconds)
                state["blocked_reason"] = block
                state["block_classifier_version"] = 2
            state["last_result"] = result
            if result == "PAGE_READ":
                state["last_page_read_at"] = now
            if state.get("in_flight_token") == token:
                state.pop("in_flight_token", None)
                state.pop("in_flight_until", None)

    def _is_blocked(self, html: str) -> bool:
        return _block_reason(html) is not None

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
            game_offer = classify_game_offer(
                title=_clean(title),
                description=None,
                price=None,
                source_verified=False,
            ).model_dump(mode="json")
            offers.append(
                ProductResult(
                    marketplace=self.marketplace,
                    title=_clean(title),
                    url=url,
                    currency="RUB",
                    confidence=0.45,
                    game_offer=game_offer,
                    raw={
                        "search_query": query,
                        "source": "rendered_search_link",
                        "game_offer": game_offer,
                    },
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
            game_offer = classify_game_offer(
                title=title,
                description=None,
                price=None,
                source_verified=False,
            ).model_dump(mode="json")
            offers.append(
                ProductResult(
                    marketplace=self.marketplace,
                    title=title,
                    url=url,
                    currency="RUB",
                    confidence=0.45,
                    game_offer=game_offer,
                    raw={
                        "search_query": query,
                        "source": "rendered_search_link",
                        "game_offer": game_offer,
                    },
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
        price, price_evidence = (None, None) if removed else _html_primary_price(soup)
        description_node = soup.select_one(
            '[data-marker="item-view/item-description"], [itemprop="description"]'
        )
        description = (
            _clean(description_node.get_text(" ", strip=True))[:6000]
            if description_node is not None
            else None
        )
        game_offer = classify_game_offer(
            title=_clean(title),
            description=" ".join(value for value in (description, price_evidence) if value),
            price=price,
            source_verified=True,
        ).model_dump(mode="json")
        return ProductResult(
            marketplace=self.marketplace,
            title=_clean(title),
            url=self.normalize_product_url(url),
            price=price,
            price_kind=str(game_offer["price_kind"]),
            game_offer=game_offer,
            currency="RUB",
            availability="removed" if removed else "available",
            confidence=0.85 if price is not None and not removed else 0.65,
            raw={
                "source": "rendered_product_page",
                "description": description,
                "price_evidence": price_evidence,
                "evidence_excerpt": body[:10000],
                "game_offer": game_offer,
            },
        )

    def _parse_accessibility_details(
        self,
        text: str,
        url: str,
        title_match: re.Match[str],
    ) -> ProductResult:
        title = _clean(title_match.group(1))
        header = _primary_accessibility_header(text, title_match.end())
        removed = "объявление снято с публикации" in header.lower()
        price, price_evidence = (None, None) if removed else _accessibility_primary_price(header, title)
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
            "price_evidence": price_evidence,
            "evidence_excerpt": _evidence_excerpt(text, title_match.start()),
        }
        game_offer = classify_game_offer(
            title=title,
            description=" ".join(value for value in (description, price_evidence) if value),
            price=price,
            source_verified=True,
        ).model_dump(mode="json")
        raw_fields["game_offer"] = game_offer
        return ProductResult(
            marketplace=self.marketplace,
            title=title,
            url=self.normalize_product_url(url),
            price=price,
            price_kind=str(game_offer["price_kind"]),
            game_offer=game_offer,
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


def _primary_accessibility_header(text: str, start: int) -> str:
    remainder = text[start : start + 2500]
    next_heading = re.search(r'^- heading ".+" \[level=[123]\]$', remainder, flags=re.MULTILINE)
    return remainder[: next_heading.start()] if next_heading else remainder


def _accessibility_primary_price(header: str, title: str) -> tuple[float | None, str | None]:
    candidates: list[tuple[float, str]] = []
    normalized_title = _clean(title).lower()
    for line in header.splitlines():
        cleaned = _clean(line)
        if "₽" not in cleaned:
            continue
        is_title_bound = normalized_title and normalized_title in cleaned.lower()
        is_price_control = bool(
            re.match(r'^- (?:button|text):?\s*"?(?:от\s+)?\d[\d\s]*\s*₽', cleaned, flags=re.IGNORECASE)
        )
        if not (is_title_bound or is_price_control):
            continue
        value = _first_price(cleaned)
        if value is not None:
            candidates.append((value, cleaned))
    distinct = {value for value, _ in candidates}
    if len(distinct) != 1:
        return None, None
    return candidates[0]


def _html_primary_price(soup: BeautifulSoup) -> tuple[float | None, str | None]:
    for selector, attr in (
        ('meta[itemprop="price"]', "content"),
        ('meta[property="product:price:amount"]', "content"),
        ('[data-marker="item-view/item-price"]', None),
        ('[itemprop="price"]', "content"),
    ):
        node = soup.select_one(selector)
        if node is None:
            continue
        raw = str(node.get(attr) or "") if attr else node.get_text(" ", strip=True)
        value = parse_price(raw)
        if value is not None:
            return value, _clean(raw)

    for payload in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(payload.string or payload.get_text() or "")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        price = _json_ld_product_price(data)
        if price is not None:
            return price, str(price)
    return None, None


def _json_ld_product_price(value: Any, *, in_product: bool = False) -> float | None:
    if isinstance(value, list):
        for item in value:
            price = _json_ld_product_price(item, in_product=in_product)
            if price is not None:
                return price
        return None
    if not isinstance(value, dict):
        return None
    item_type = value.get("@type")
    types = {str(item_type).lower()} if not isinstance(item_type, list) else {str(item).lower() for item in item_type}
    is_product = in_product or "product" in types
    if is_product:
        offers = value.get("offers")
        if isinstance(offers, dict):
            price = parse_price(offers.get("price"))
            if price is not None:
                return price
        price = parse_price(value.get("price"))
        if price is not None:
            return price
    for child in value.values():
        if isinstance(child, (dict, list)):
            price = _json_ld_product_price(child, in_product=is_product)
            if price is not None:
                return price
    return None


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


_ACCESS_STOP = {"AVITO_IP_BLOCKED", "AVITO_IP_COOLDOWN", "AVITO_ACCESS_COOLDOWN",
                "CAPTCHA_OR_BLOCKED", "AVITO_REQUEST_IN_PROGRESS", "AVITO_RATE_LIMIT_WAIT",
                "AVITO_ACCESS_STATE_INVALID"}


def _cooldown_warning(state: dict) -> str:
    return ("AVITO_IP_COOLDOWN" if state.get("blocked_reason") in (None, "AVITO_IP_BLOCKED")
            else "AVITO_ACCESS_COOLDOWN")


def _iso_time(value: float) -> str | None:
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value else None


def _block_reason(snapshot: str) -> str | None:
    """Classify actual challenge pages, not security words in a listing description."""
    soup = BeautifulSoup(snapshot, "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    headings = [node.get_text(" ", strip=True) for node in soup.select("title, h1, h2, [role=dialog]")]
    headings += re.findall(r'(?:heading|dialog) "([^"\n]+)"', snapshot)
    # Text-only error pages have no product/detail heading to protect.
    if not headings:
        text = soup.get_text(" ", strip=True)
        if len(text) < 1600 and not re.search(r'/url: [^\s]+_\d+|item-view|itemprop=.price', snapshot):
            headings = [text]
    for value in headings:
        value = re.sub(r"\s+", " ", value).strip().lower()
        if re.match(r"^(?:доступ ограничен[: —-]*)?проблема с ip\b", value):
            return "AVITO_IP_BLOCKED"
        if re.match(r"^(?:captcha\b|подтвердите[,]? что вы человек|проверка[, :—-]+(?:что вы|браузера)|вы не робот|проверим,? что вы|докажите,? что вы|доступ ограничен)", value):
            return "AVITO_CHALLENGE_REQUIRED"
        if re.match(r"^(?:access denied|forbidden|доступ запрещ[её]н)\b", value):
            return "AVITO_ACCESS_DENIED"
        if re.match(r"^(?:пожалуйста[, ]+)?(?:выключите|отключите|отключить) vpn\b", value):
            return "AVITO_NETWORK_RESTRICTION"
        if re.match(r"^проверяем браузер\b", value):
            return "AVITO_BROWSER_CHECK_PENDING"
    return None


class _locked_state:
    """Small cross-process state transaction shared by both Hermes profiles."""

    def __init__(self, path: Path, *, write: bool = True):
        self.path = path
        self.lock_path = path.with_suffix(path.suffix + ".lock")
        self.lock_file = None
        self.state: dict[str, object] = {}
        self.write = write

    def __enter__(self) -> dict[str, object]:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        self.lock_file = os.fdopen(descriptor, "r+")
        _lock_file(self.lock_file)
        try:
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                payload = {}
            if not isinstance(payload, dict):
                raise ValueError("Invalid Avito access state")
            for key in ("blocked_until", "blocked_at", "last_request_at", "in_flight_until", "last_page_read_at"):
                _as_float(payload.get(key))
            self.state = payload
        except BaseException:
            _unlock_file(self.lock_file)
            self.lock_file.close()
            raise
        return self.state

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        try:
            if exc_type is None and self.write:
                descriptor, temporary = tempfile.mkstemp(prefix=self.path.name + ".", dir=self.path.parent)
                try:
                    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                        json.dump(self.state, output, sort_keys=True)
                        output.flush()
                        os.fsync(output.fileno())
                    os.replace(temporary, self.path)
                    if hasattr(os, "O_DIRECTORY"):
                        directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
                        try:
                            os.fsync(directory)
                        finally:
                            os.close(directory)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
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
    if value is None:
        return 0.0
    try:
        number = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid Avito access timestamp") from exc
    if not math.isfinite(number) or number < 0 or number > 253402300799:
        raise ValueError("Invalid Avito access timestamp")
    return number
