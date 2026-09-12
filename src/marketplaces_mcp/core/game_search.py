"""Bounded Avito discovery and explicit detail verification for physical games."""
from __future__ import annotations

import asyncio
import math
import re
from datetime import datetime, timedelta, timezone

from marketplaces_mcp.core.game_offers import classify_game_offer
from marketplaces_mcp.core.normalize import normalize_title, parse_price

_STOP = {"AVITO_IP_BLOCKED", "AVITO_IP_COOLDOWN", "AVITO_ACCESS_COOLDOWN",
         "AVITO_REQUEST_IN_PROGRESS", "AVITO_RATE_LIMIT_WAIT", "AVITO_ACCESS_STATE_INVALID",
         "CAPTCHA_OR_BLOCKED", "CHROMIUM_CDP_FAILED"}
_DETAIL_SOURCES = {"rendered_product_page", "camofox_accessibility_snapshot"}


async def search_game_offers(adapter, game_title: str, *, max_price: float | None = None,
                             include_game_key_cards: bool = True, limit: int = 8,
                             verify_details: int = 2, strategy: str = "auto") -> dict:
    """Return alert candidates only after exact-title, live-detail and media checks.

    No scheduler, messages, purchases, or persistent price baselines are created.
    Prices exclude unverified delivery fees. Missing detail never qualifies.
    """
    title = game_title.strip()
    response = {"game_title": title, "checked_at": datetime.now(timezone.utc).isoformat(),
                "eligible_offers": {"physical_cartridge": [], "game_key_card": []},
                "candidates": [], "rejected": [], "warnings": [],
                "source_url": adapter.build_search_url(f"{title} Nintendo Switch 2"),
                "price_scope": "Listing price only; delivery and seller claims require verification"}
    if len(title) < 3 or len(title) > 160 or (max_price is not None and (not math.isfinite(max_price) or max_price <= 0)):
        response["warnings"] = ["INVALID_GAME_REQUEST"]
        return response
    if hasattr(adapter, "access_status") and strategy != "fixture":
        response["access_status"] = await adapter.access_status()
        state = response["access_status"]
        if state.get("state") in {"cooldown", "busy", "error"}:
            if state["state"] == "cooldown":
                warning = ("AVITO_IP_COOLDOWN" if state.get("reason") in
                           {"AVITO_IP_BLOCKED", "legacy_unclassified_block"} else "AVITO_ACCESS_COOLDOWN")
            else:
                warning = "AVITO_REQUEST_IN_PROGRESS" if state["state"] == "busy" else "AVITO_ACCESS_STATE_INVALID"
            response["warnings"] = [warning, "NO_VERIFIED_GAME_PRICE_MATCH"]
            return response
    formats = ("physical_cartridge", "game_key_card") if include_game_key_cards else ("physical_cartridge",)
    try:
        products, warnings, url = await asyncio.wait_for(
            adapter.search(f"{title} Nintendo Switch 2", limit=max(1, min(limit, 10)), strategy=strategy), 150)
    except Exception as exc:
        response["warnings"] = [f"AVITO_SEARCH_FAILED_{type(exc).__name__}"]
        return response
    response["source_url"] = url
    response["warnings"].extend(warnings)
    remaining = max(0, min(verify_details, 2))
    stop = bool(_STOP.intersection(warnings))
    for product in products[:max(1, min(limit, 10))]:
        raw = product.raw or {}
        classification = classify_game_offer(product.title, raw.get("description"), product.price,
            target_title=title, allowed_media_formats=formats)
        # Discard known mismatches cheaply, preserve unknown leads for inspection.
        if classification.decision == "rejected":
            response["rejected"].append({"url": product.url, "title": product.title,
                                         "game_offer": classification.model_dump()})
            continue
        verified = False
        if remaining and not stop and strategy != "fixture":
            remaining -= 1
            requested_url = product.url
            try:
                detail, detail_warnings, detail_source_url = await asyncio.wait_for(
                    adapter.product_details(product.url, strategy=strategy), 120)
            except Exception as exc:
                detail, detail_warnings = None, [f"AVITO_DETAILS_FAILED_{type(exc).__name__}"]
                detail_source_url = None
            response["warnings"].extend(detail_warnings)
            stop = bool(_STOP.intersection(detail_warnings))
            if detail:
                product = detail
                raw = product.raw or {}
                identity_matches = (
                    _canonical_url(adapter, requested_url) == _canonical_url(adapter, product.url)
                    and _canonical_url(adapter, requested_url) == _canonical_url(adapter, detail_source_url)
                )
                if not identity_matches:
                    response["warnings"].append("AVITO_DETAIL_IDENTITY_MISMATCH")
                verified = (
                    not stop
                    and identity_matches
                    and raw.get("source") in _DETAIL_SOURCES
                    and not {"PRICE_UNVERIFIED", "INDEX_DISCOVERY_ONLY"}.intersection(detail_warnings)
                    and str(product.availability or "").lower() == "available"
                    and product.price_kind == "exact"
                    and product.price_condition is None
                    and _valid_price(product.price)
                    and str(product.currency or "").upper() == "RUB"
                    and _price_evidence_matches(raw.get("price_evidence"), product.price)
                    and _fresh_observation(product.scraped_at)
                )
        description = " ".join(str(raw.get(k) or "") for k in ("description", "price_evidence"))
        classification = classify_game_offer(product.title, description, product.price,
            target_title=title, source_verified=verified, allowed_media_formats=formats)
        if not _strict_title_match(product.title, title):
            classification.alert_eligible = False
            classification.decision = "rejected"
            classification.title_match = "mismatch"
            classification.reasons.append("TARGET_TITLE_STRICT_MISMATCH")
        if product.price_kind != "exact":
            classification.alert_eligible = False
            if classification.decision != "rejected":
                classification.decision = "unknown"
            classification.reasons.append("PRICE_NOT_EXACT")
        if not _valid_price(product.price):
            classification.alert_eligible = False
            if classification.decision != "rejected":
                classification.decision = "unknown"
            classification.reasons.append("PRICE_INVALID_OR_MISSING")
        if classification.alert_eligible and max_price is not None and product.price > max_price:
            classification.alert_eligible = False
            classification.reasons.append("ABOVE_MAX_PRICE")
        product.game_offer = classification.model_dump()
        obj = product.model_dump(mode="json")
        if classification.alert_eligible:
            response["eligible_offers"][classification.media_format].append(obj)
        elif classification.decision == "rejected":
            response["rejected"].append(obj)
        else:
            if max_price is not None and product.price is not None and product.price > max_price:
                obj["budget_status"] = "above_threshold"
            response["candidates"].append(obj)
    for offers in response["eligible_offers"].values():
        offers.sort(key=lambda item: item["price"])
    response["warnings"] = sorted(set(response["warnings"]))
    if not any(response["eligible_offers"].values()):
        response["warnings"].append("NO_VERIFIED_GAME_PRICE_MATCH")
    if hasattr(adapter, "access_status") and strategy != "fixture":
        response["access_status"] = await adapter.access_status()
    return response


def _canonical_url(adapter, value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(adapter.normalize_product_url(str(value))).rstrip("/")
    except Exception:
        return str(value).split("?", 1)[0].split("#", 1)[0].rstrip("/")


def _valid_price(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def _fresh_observation(value: object) -> bool:
    if not isinstance(value, datetime) or value.tzinfo is None:
        return False
    age = datetime.now(timezone.utc) - value.astimezone(timezone.utc)
    return timedelta(0) <= age <= timedelta(minutes=10)


def _price_evidence_matches(evidence: object, price: object) -> bool:
    if not _valid_price(price) or not isinstance(evidence, str) or not evidence.strip():
        return False
    ruble_values = {
        parse_price(match.group(1))
        for match in re.finditer(
            r"(\d{1,3}(?:[\s\u00a0\u202f]+\d{3})+|\d+)\s*(?:₽|руб\.?|rub\b)",
            evidence,
            re.I,
        )
    }
    ruble_values.discard(None)
    if ruble_values:
        return len(ruble_values) == 1 and math.isclose(next(iter(ruble_values)), float(price))
    semantic_value = parse_price(evidence) if re.fullmatch(r"\s*\d[\d\s.,]*\s*", evidence) else None
    return semantic_value is not None and math.isclose(semantic_value, float(price))


def _strict_title_match(listing_title: str, target_title: str) -> bool:
    """Require the same game identity after removing marketplace-only words."""
    ignored = {
        "nintendo", "switch", "свитч", "свич", "ns", "ns2", "cartridge", "physical",
        "copy", "game", "key", "card", "ключ", "карта", "картридж", "игра",
        "edition", "издание", "продам", "продаю",
    }
    listing_metadata = {
        "новый", "новая", "новое", "new", "б", "у", "бу", "used", "sealed",
        "запечатанный", "запечатанная", "русская", "русские", "русский", "версия",
        "субтитры", "озвучка", "original", "оригинал",
    }

    def identity(value: str) -> list[str]:
        normalized = normalize_title(value)
        normalized = re.sub(r"\b(?:nintendo\s+)?switch\s*2\b", " ", normalized)
        normalized = re.sub(r"\b(?:свитч|свич)\s*2\b|\bns\s*2\b", " ", normalized)
        return [token for token in normalize_title(normalized).split() if token not in ignored]

    target = identity(target_title)
    listing = [token for token in identity(listing_title) if token not in listing_metadata or token in target]
    return bool(target) and target == listing
