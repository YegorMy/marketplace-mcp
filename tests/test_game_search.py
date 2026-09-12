from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta, timezone

import pytest

from marketplaces_mcp.core.game_search import search_game_offers
from marketplaces_mcp.core.models import ProductResult


BASE = "https://www.avito.ru/moskva/igry/offer_"


def _lead(identifier: int = 1, title: str = "Mario Kart World Nintendo Switch 2 картридж"):
    return ProductResult(
        marketplace="avito",
        title=title,
        url=f"{BASE}{identifier}",
        raw={"source": "rendered_search_link"},
    )


def _detail(
    identifier: int = 1,
    *,
    title: str = "Mario Kart World Nintendo Switch 2 картридж",
    price: float | None = 5990,
    price_kind: str = "exact",
    price_condition: str | None = None,
    price_evidence: str | None = "Mario Kart World Nintendo Switch 2 5 990 ₽",
    description: str = "Физический картридж.",
    availability: str | None = "available",
    source: str = "camofox_accessibility_snapshot",
    currency: str = "RUB",
    scraped_at: datetime | None = None,
):
    return ProductResult(
        marketplace="avito",
        title=title,
        url=f"{BASE}{identifier}",
        price=price,
        price_kind=price_kind,
        price_condition=price_condition,
        currency=currency,
        availability=availability,
        scraped_at=scraped_at or datetime.now(timezone.utc),
        raw={
            "source": source,
            "description": description,
            "price_evidence": price_evidence,
        },
    )


class FakeAdapter:
    def __init__(self, leads, details=None, *, search_warnings=None, search_error=None):
        self.leads = leads
        self.details = details or {}
        self.search_warnings = search_warnings or []
        self.search_error = search_error
        self.detail_calls: list[str] = []

    def build_search_url(self, query):
        return "https://www.avito.ru/moskva?q=" + query.replace(" ", "+")

    def normalize_product_url(self, url):
        return str(url).split("?", 1)[0].rstrip("/")

    async def search(self, query, limit, strategy):
        if self.search_error:
            raise self.search_error
        return self.leads[:limit], list(self.search_warnings), self.build_search_url(query)

    async def product_details(self, url, strategy):
        self.detail_calls.append(url)
        value = self.details[url]
        if isinstance(value, BaseException):
            raise value
        if len(value) == 2:
            detail, warnings = value
            return detail, warnings, url
        return value


def _run(adapter, **kwargs):
    return asyncio.run(search_game_offers(adapter, "Mario Kart World", **kwargs))


def _eligible(response):
    return response["eligible_offers"]["physical_cartridge"]


def test_verified_exact_detail_qualifies():
    lead = _lead()
    adapter = FakeAdapter([lead], {lead.url: (_detail(), [])})

    response = _run(adapter)

    assert len(_eligible(response)) == 1
    assert _eligible(response)[0]["price"] == 5990
    assert "NO_VERIFIED_GAME_PRICE_MATCH" not in response["warnings"]


@pytest.mark.parametrize(
    ("returned_url", "source_url"),
    [
        (f"{BASE}2", f"{BASE}1"),
        (f"{BASE}1", f"{BASE}2"),
    ],
)
def test_detail_identity_mismatch_never_qualifies(returned_url: str, source_url: str):
    lead = _lead(1)
    detail = _detail(1)
    detail.url = returned_url
    adapter = FakeAdapter([lead], {lead.url: (detail, [], source_url)})

    response = _run(adapter)

    assert not _eligible(response)
    assert "AVITO_DETAIL_IDENTITY_MISMATCH" in response["warnings"]
    assert "NO_VERIFIED_GAME_PRICE_MATCH" in response["warnings"]


@pytest.mark.parametrize(
    ("strategy", "warnings"),
    [
        ("fixture", []),
        ("auto", ["AVITO_IP_COOLDOWN"]),
        ("auto", ["AVITO_IP_BLOCKED", "CAPTCHA_OR_BLOCKED"]),
    ],
)
def test_fixture_and_blocked_searches_do_not_read_details_or_alert(strategy: str, warnings: list[str]):
    lead = _lead()
    adapter = FakeAdapter([lead], {lead.url: (_detail(), [])}, search_warnings=warnings)

    response = _run(adapter, strategy=strategy)

    assert adapter.detail_calls == []
    assert not _eligible(response)
    assert "NO_VERIFIED_GAME_PRICE_MATCH" in response["warnings"]


def test_unverified_index_lead_without_detail_budget_never_alerts():
    lead = _lead()
    adapter = FakeAdapter([lead], search_warnings=["INDEX_DISCOVERY_ONLY", "PRICE_UNVERIFIED"])

    response = _run(adapter, verify_details=0)

    assert adapter.detail_calls == []
    assert not _eligible(response)


@pytest.mark.parametrize(
    "detail_title",
    [
        "Mario Kart 8 Nintendo Switch 2 картридж",
        "Mario Kart 8 Deluxe + Zelda Nintendo Switch 2 картридж",
        "Mario Kart 8 Ultimate Edition Nintendo Switch 2 картридж",
    ],
)
def test_exact_title_guard_rejects_missing_extra_or_different_edition(detail_title: str):
    lead = _lead(title="Mario Kart 8 Deluxe Nintendo Switch 2 картридж")
    detail = _detail(title=detail_title)
    detail.url = lead.url
    adapter = FakeAdapter([lead], {lead.url: (detail, [])})

    response = asyncio.run(search_game_offers(adapter, "Mario Kart 8 Deluxe"))

    assert not _eligible(response)
    assert any(
        "TARGET_TITLE_STRICT_MISMATCH" in item["game_offer"]["reasons"]
        for item in response["rejected"]
    )


def test_exact_title_guard_preserves_game_number_after_removing_switch_2():
    lead = _lead(title="Overcooked Nintendo Switch 2 картридж")
    detail = _detail(title="Overcooked Nintendo Switch 2 картридж")
    detail.url = lead.url
    adapter = FakeAdapter([lead], {lead.url: (detail, [])})

    response = asyncio.run(search_game_offers(adapter, "Overcooked 2"))

    assert not _eligible(response)


def test_exact_title_guard_does_not_treat_new_as_marketing_for_a_game_title():
    lead = _lead(title="Super Mario Bros U Deluxe Nintendo Switch 2 картридж")
    detail = _detail(title=lead.title)
    detail.url = lead.url
    adapter = FakeAdapter([lead], {lead.url: (detail, [])})

    response = asyncio.run(search_game_offers(adapter, "New Super Mario Bros U Deluxe"))

    assert not _eligible(response)


def test_exact_title_guard_accepts_literal_edition_suffix():
    lead = _lead(title="Mario Kart 8 Deluxe Nintendo Switch 2 картридж")
    detail = _detail(title="Mario Kart 8 Deluxe Edition Nintendo Switch 2 картридж")
    detail.url = lead.url
    adapter = FakeAdapter([lead], {lead.url: (detail, [])})

    response = asyncio.run(search_game_offers(adapter, "Mario Kart 8 Deluxe"))

    assert len(_eligible(response)) == 1


@pytest.mark.parametrize(
    "detail_title",
    [
        "Mario Kart World Nintendo Switch 2 Новый Картридж",
        "Mario Kart World Nintendo Switch 2 картридж, русская версия",
        "Mario Kart World Nintendo Switch 2 картридж б/у",
    ],
)
def test_exact_title_guard_accepts_generic_condition_and_language_metadata(detail_title: str):
    lead = _lead(title=detail_title)
    detail = _detail(title=detail_title)
    detail.url = lead.url
    adapter = FakeAdapter([lead], {lead.url: (detail, [])})

    response = _run(adapter)

    assert len(_eligible(response)) == 1


@pytest.mark.parametrize("price", [None, 0, -1, math.nan, math.inf])
def test_missing_zero_negative_or_non_finite_price_never_alerts(price: float | None):
    lead = _lead()
    adapter = FakeAdapter([lead], {lead.url: (_detail(price=price), [])})

    response = _run(adapter)

    assert not _eligible(response)
    assert response["candidates"]
    assert response["candidates"][0]["game_offer"]["alert_eligible"] is False


@pytest.mark.parametrize(
    ("price_kind", "price_evidence"),
    [
        ("unknown", "5 990 ₽"),
        ("conditional", "5 990 ₽"),
        ("from", "от 5 990 ₽"),
        ("exact", None),
        ("exact", "4 990 ₽"),
        ("exact", "5 990 ₽ и 4 990 ₽"),
    ],
)
def test_unverified_conditional_stale_or_conflicting_price_evidence_never_alerts(
    price_kind: str,
    price_evidence: str | None,
):
    lead = _lead()
    adapter = FakeAdapter(
        [lead],
        {lead.url: (_detail(price_kind=price_kind, price_evidence=price_evidence), [])},
    )

    response = _run(adapter)

    assert not _eligible(response)


def test_price_condition_and_stale_detail_never_alert():
    conditional_lead, stale_lead = _lead(1), _lead(2)
    adapter = FakeAdapter(
        [conditional_lead, stale_lead],
        {
            conditional_lead.url: (
                _detail(1, price_condition="Requires seller membership"),
                [],
            ),
            stale_lead.url: (
                _detail(2, scraped_at=datetime.now(timezone.utc) - timedelta(hours=1)),
                [],
            ),
        },
    )

    response = _run(adapter)

    assert not _eligible(response)


@pytest.mark.parametrize(
    ("description", "price_kind"),
    [
        ("Цифровой код активации и картридж.", "exact"),
        ("Доступ к аккаунту с игрой.", "exact"),
        ("Физический картридж. Цена указана за одну игру.", "exact"),
        ("Физический картридж.", "from"),
    ],
)
def test_digital_conflict_account_and_per_item_offers_never_alert(
    description: str,
    price_kind: str,
):
    lead = _lead()
    evidence = "от 5 990 ₽" if price_kind == "from" else "5 990 ₽"
    adapter = FakeAdapter(
        [lead],
        {lead.url: (_detail(description=description, price_kind=price_kind, price_evidence=evidence), [])},
    )

    response = _run(adapter)

    assert not _eligible(response)


def test_game_key_cards_are_separate_and_policy_controlled():
    lead = _lead(title="Mario Kart World Nintendo Switch 2 Game-Key Card")
    detail = _detail(
        title=lead.title,
        description="Game-Key Card, download required.",
    )
    adapter = FakeAdapter([lead], {lead.url: (detail, [])})

    included = _run(adapter, include_game_key_cards=True)
    excluded = _run(adapter, include_game_key_cards=False)

    assert len(included["eligible_offers"]["game_key_card"]) == 1
    assert not included["eligible_offers"]["physical_cartridge"]
    assert not excluded["eligible_offers"]["game_key_card"]


def test_max_price_boundary_and_above_threshold_status():
    lead = _lead()
    adapter = FakeAdapter([lead], {lead.url: (_detail(price=5990), [])})

    at_limit = _run(adapter, max_price=5990)
    above_limit = _run(adapter, max_price=5989)

    assert len(_eligible(at_limit)) == 1
    assert not _eligible(above_limit)
    assert above_limit["candidates"][0]["budget_status"] == "above_threshold"
    assert above_limit["candidates"][0]["game_offer"]["alert_eligible"] is False
    assert "ABOVE_MAX_PRICE" in above_limit["candidates"][0]["game_offer"]["reasons"]


@pytest.mark.parametrize("max_price", [0, -1, math.nan, math.inf])
def test_invalid_max_price_returns_without_network(max_price: float):
    adapter = FakeAdapter([_lead()])

    response = _run(adapter, max_price=max_price)

    assert response["warnings"] == ["INVALID_GAME_REQUEST"]
    assert adapter.detail_calls == []


def test_detail_budget_is_hard_capped_at_two():
    leads = [_lead(index) for index in range(1, 5)]
    details = {lead.url: (_detail(index + 1), []) for index, lead in enumerate(leads)}
    adapter = FakeAdapter(leads, details)

    response = _run(adapter, verify_details=99, limit=8)

    assert len(adapter.detail_calls) == 2
    assert len(_eligible(response)) == 2
    assert len(response["candidates"]) == 2


def test_detail_exception_is_isolated_and_next_candidate_can_qualify():
    first, second = _lead(1), _lead(2)
    adapter = FakeAdapter(
        [first, second],
        {
            first.url: RuntimeError("fixture failure"),
            second.url: (_detail(2), []),
        },
    )

    response = _run(adapter)

    assert len(adapter.detail_calls) == 2
    assert len(_eligible(response)) == 1
    assert "AVITO_DETAILS_FAILED_RuntimeError" in response["warnings"]


def test_search_exception_returns_structured_empty_result():
    adapter = FakeAdapter([], search_error=RuntimeError("fixture failure"))

    response = _run(adapter)

    assert not _eligible(response)
    assert response["warnings"] == ["AVITO_SEARCH_FAILED_RuntimeError"]


@pytest.mark.parametrize("availability", [None, "removed", "unavailable", "sold", "out_of_stock"])
def test_unavailable_or_unknown_availability_never_alerts(availability: str | None):
    lead = _lead()
    adapter = FakeAdapter([lead], {lead.url: (_detail(availability=availability), [])})

    response = _run(adapter)

    assert not _eligible(response)


def test_detail_block_stops_remaining_detail_budget():
    first, second = _lead(1), _lead(2)
    adapter = FakeAdapter(
        [first, second],
        {
            first.url: (None, ["AVITO_IP_COOLDOWN"]),
            second.url: (_detail(2), []),
        },
    )

    response = _run(adapter)

    assert adapter.detail_calls == [first.url]
    assert not _eligible(response)
    assert "AVITO_IP_COOLDOWN" in response["warnings"]
