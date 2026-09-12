from __future__ import annotations

import pytest

from marketplaces_mcp.adapters.avito import AvitoAdapter
from marketplaces_mcp.core.game_offers import classify_game_offer


def _classify(
    title: str,
    description: str = "",
    price: float | None = 5990,
    *,
    target_title: str | None = "Mario Kart World",
    source_verified: bool = True,
    allowed_media_formats=("physical_cartridge",),
    require_full_game: bool = False,
):
    return classify_game_offer(
        title,
        description,
        price,
        target_title=target_title,
        source_verified=source_verified,
        allowed_media_formats=allowed_media_formats,
        require_full_game=require_full_game,
    )


def test_explicit_full_switch_2_cartridge_is_alert_eligible():
    result = _classify(
        "Mario Kart World Nintendo Switch 2 — картридж",
        "Полная игра на картридже, не требует дополнительной загрузки.",
    )

    assert result.decision == "qualifies"
    assert result.alert_eligible is True
    assert result.media_format == "physical_cartridge"
    assert result.cartridge_data == "full_game"
    assert result.platform == "switch_2"
    assert result.price_kind == "exact"
    assert result.title_match == "match"
    assert {item.field for item in result.evidence} >= {
        "media_format",
        "cartridge_data",
        "platform",
        "price_kind",
        "title_match",
    }


def test_bare_physical_cartridge_can_qualify_without_inventing_data_subtype():
    result = _classify("Mario Kart World Nintendo Switch 2 новый картридж")

    assert result.decision == "qualifies"
    assert result.media_format == "physical_cartridge"
    assert result.cartridge_data == "unknown"
    assert result.alert_eligible is True
    assert "CARTRIDGE_DATA_UNVERIFIED" in result.reasons


def test_full_game_only_policy_keeps_bare_cartridge_unknown():
    result = _classify(
        "Mario Kart World Nintendo Switch 2 новый картридж",
        require_full_game=True,
    )

    assert result.decision == "unknown"
    assert result.alert_eligible is False
    assert result.cartridge_data == "unknown"


def test_game_key_card_can_only_qualify_when_explicitly_allowed():
    result = _classify(
        "Mario Kart World Nintendo Switch 2 Game-Key Card",
        "Physical card, download required.",
        allowed_media_formats=("physical_cartridge", "game_key_card"),
    )

    assert result.decision == "qualifies"
    assert result.alert_eligible is True
    assert result.media_format == "game_key_card"
    assert result.cartridge_data == "download_required"


@pytest.mark.parametrize(
    ("title", "description", "media_format", "cartridge_data"),
    [
        (
            "Mario Kart World Nintendo Switch 2 Game-Key Card",
            "Physical card; download required.",
            "game_key_card",
            "download_required",
        ),
        (
            "Mario Kart World Switch 2 ключ-карта",
            "Для запуска требуется загрузка игры.",
            "game_key_card",
            "download_required",
        ),
        (
            "Mario Kart World Nintendo Switch 2 цифровой код",
            "Код активации для eShop.",
            "digital_code",
            "unknown",
        ),
        (
            "Mario Kart World Switch 2 цифровая версия",
            "Моментальная доставка после оплаты.",
            "digital_code",
            "unknown",
        ),
        (
            "Mario Kart World Switch 2",
            "Продам цифровую версию игры.",
            "digital_code",
            "unknown",
        ),
        (
            "Mario Kart World Switch 2 — цифра",
            "Без физического носителя.",
            "digital_code",
            "unknown",
        ),
        (
            "Mario Kart World Switch 2 digital version",
            "No physical cartridge.",
            "digital_code",
            "unknown",
        ),
        (
            "Mario Kart World Switch 2",
            "Доступ к аккаунту, игра уже установлена.",
            "account_access",
            "unknown",
        ),
        (
            "Установка Mario Kart World на Switch 2",
            "Услуга активации игры.",
            "service",
            "unknown",
        ),
        (
            "Коробка Mario Kart World Switch 2 без картриджа",
            "Пустая коробка, игры нет.",
            "empty_case",
            "unknown",
        ),
        (
            "Чехол Mario Kart World для Nintendo Switch 2",
            "Protective case accessory.",
            "accessory",
            "unknown",
        ),
    ],
)
def test_non_full_cartridge_formats_are_rejected(
    title: str,
    description: str,
    media_format: str,
    cartridge_data: str,
):
    result = _classify(title, description)

    assert result.decision == "rejected"
    assert result.alert_eligible is False
    assert result.media_format == media_format
    assert result.cartridge_data == cartridge_data


def test_conflicting_physical_and_digital_claims_are_unknown():
    result = _classify(
        "Mario Kart World Switch 2 картридж",
        "Цифровой код активации. Полная игра на картридже.",
    )

    assert result.decision == "unknown"
    assert result.alert_eligible is False
    assert result.media_format == "unknown"
    assert "CONFLICTING_MEDIA_EVIDENCE" in result.reasons


@pytest.mark.parametrize(
    ("description", "expected_kind"),
    [
        ("Цена от 3 000 ₽, зависит от игры.", "from_price"),
        ("Цена указана за одну игру.", "per_item"),
        ("Несколько игр, цены разные, уточняйте.", "multi_item_ambiguous"),
        ("Games available, multiple cartridges.", "multi_item_ambiguous"),
        ("Игры Nintendo Switch 2: Mario / Zelda / Donkey Kong.", "multi_item_ambiguous"),
        ("Mario Kart World / Zelda, картриджи для Switch 2.", "multi_item_ambiguous"),
    ],
)
def test_conditional_or_multiple_game_prices_are_rejected(description: str, expected_kind: str):
    result = _classify(
        "Mario Kart World Nintendo Switch 2 картридж",
        f"Полная игра на картридже, без дополнительной загрузки. {description}",
    )

    assert result.decision == "rejected"
    assert result.price_kind == expected_kind
    assert result.alert_eligible is False


def test_missing_price_is_unknown():
    result = _classify(
        "Mario Kart World Nintendo Switch 2 картридж",
        "Полная игра на картридже, без загрузки.",
        price=None,
    )

    assert result.decision == "unknown"
    assert result.price_kind == "unknown"
    assert result.alert_eligible is False


def test_unverified_search_source_never_qualifies():
    result = _classify(
        "Mario Kart World Nintendo Switch 2 картридж",
        "Полная игра на картридже, без загрузки.",
        source_verified=False,
    )

    assert result.decision == "unknown"
    assert result.alert_eligible is False
    assert "DETAIL_SOURCE_NOT_VERIFIED" in result.reasons


@pytest.mark.parametrize(
    ("title", "description", "platform", "decision"),
    [
        ("Mario Kart World Nintendo Switch картридж", "Полная игра на картридже.", "switch", "rejected"),
        (
            "Mario Kart World Nintendo Switch картридж",
            "Полная игра на картридже. Совместима с Nintendo Switch 2.",
            "both",
            "qualifies",
        ),
        (
            "Mario Kart World cartridge",
            "Full game on cartridge. Platform not stated.",
            "unknown",
            "unknown",
        ),
        (
            "Mario Kart World Nintendo Switch 2 cartridge",
            "Full game on cartridge. Not compatible with Nintendo Switch 2.",
            "switch",
            "rejected",
        ),
    ],
)
def test_platform_evidence_is_not_inferred(
    title: str,
    description: str,
    platform: str,
    decision: str,
):
    result = _classify(title, description)

    assert result.platform == platform
    assert result.decision == decision
    assert result.alert_eligible is (decision == "qualifies")


def test_target_game_title_must_match():
    result = _classify(
        "Donkey Kong Bananza Nintendo Switch 2 картридж",
        "Полная игра на картридже, без загрузки.",
    )

    assert result.decision == "rejected"
    assert result.title_match == "mismatch"
    assert result.alert_eligible is False
    assert "TARGET_TITLE_MISMATCH" in result.reasons


def test_target_title_omission_keeps_otherwise_valid_offer_unknown():
    result = _classify(
        "Mario Kart World Nintendo Switch 2 картридж",
        "Полная игра на картридже, без загрузки.",
        target_title=None,
    )

    assert result.decision == "unknown"
    assert result.title_match == "unknown"


def test_non_game_product_stays_unknown():
    result = _classify("Nintendo Switch 2 консоль 256 ГБ", "Новая приставка в коробке.")

    assert result.decision == "unknown"
    assert result.media_format == "unknown"
    assert result.alert_eligible is False
    assert "NOT_IDENTIFIED_AS_GAME_OFFER" in result.reasons


def test_negated_account_and_game_key_terms_do_not_cause_false_rejection():
    result = _classify(
        "Mario Kart World Nintendo Switch 2 картридж",
        "Полная игра на картридже. Не аккаунт, не game-key card, без загрузки.",
    )

    assert result.decision == "qualifies"
    assert result.media_format == "physical_cartridge"
    assert result.cartridge_data == "full_game"


def test_avito_search_result_is_deduplicated_and_never_alerts_from_title_only():
    snapshot = """
- link "Mario Kart World Nintendo Switch 2 Новый Картридж":
  - /url: /sankt-peterburg/igry_pristavki_i_programmy/mario_kart_world_nintendo_switch_2_8011309926
- link "Mario Kart World Nintendo Switch 2 Новый Картридж":
  - /url: /sankt-peterburg/igry_pristavki_i_programmy/mario_kart_world_nintendo_switch_2_8011309926
"""
    products = AvitoAdapter().parse_search_results(snapshot, query="Mario Kart World Switch 2")

    assert len(products) == 1
    assert products[0].price is None
    assert products[0].raw is not None
    classification = products[0].raw["game_offer"]
    assert products[0].game_offer == classification
    assert classification["source_verified"] is False
    assert classification["alert_eligible"] is False


def test_avito_accessibility_price_is_bound_to_primary_offer():
    snapshot = """
- heading "Mario Kart World Nintendo Switch 2 картридж" [level=1]
- button
- text: Mario Kart World Nintendo Switch 2 картридж 5 990 ₽ Пользователь
- button "Купить"
- heading "Описание" [level=2]
- paragraph: "Полная игра на картридже, без дополнительной загрузки."
- heading "Похожие объявления" [level=3]
- text: 3 000 ₽
"""
    product = AvitoAdapter().parse_product_details(
        snapshot,
        "https://www.avito.ru/moskva/igry/mario_kart_world_8011309926",
    )

    assert product is not None
    assert product.price == 5990
    assert product.raw is not None
    assert "5 990 ₽" in product.raw["price_evidence"]
    assert product.raw["game_offer"]["alert_eligible"] is False
    assert product.raw["game_offer"]["title_match"] == "unknown"


def test_avito_does_not_take_price_only_from_similar_offer_section():
    snapshot = """
- heading "Mario Kart World Nintendo Switch 2 картридж" [level=1]
- button "Написать"
- heading "Описание" [level=2]
- paragraph: "Полная игра на картридже."
- heading "Похожие объявления" [level=3]
- text: 3 000 ₽
"""
    product = AvitoAdapter().parse_product_details(
        snapshot,
        "https://www.avito.ru/moskva/igry/mario_kart_world_8011309926",
    )

    assert product is not None
    assert product.price is None
    assert product.raw is not None
    assert product.raw["price_evidence"] is None


def test_avito_conflicting_primary_prices_are_not_guessed():
    snapshot = """
- heading "Mario Kart World Nintendo Switch 2 картридж" [level=1]
- text: Mario Kart World Nintendo Switch 2 картридж 5 990 ₽ Пользователь
- button "4 990 ₽"
- heading "Описание" [level=2]
- paragraph: "Полная игра на картридже."
"""
    product = AvitoAdapter().parse_product_details(
        snapshot,
        "https://www.avito.ru/moskva/igry/mario_kart_world_8011309926",
    )

    assert product is not None
    assert product.price is None


def test_avito_html_uses_semantic_primary_price_and_ignores_body_prices():
    html = """
<html><head>
  <meta property="og:title" content="Mario Kart World Nintendo Switch 2 картридж">
  <meta itemprop="price" content="5990">
</head><body>
  <div data-marker="item-view/item-description">Полная игра на картридже, без загрузки.</div>
  <section class="similar">Похожие объявления от 3 000 ₽</section>
</body></html>
"""
    product = AvitoAdapter().parse_product_details(
        html,
        "https://www.avito.ru/moskva/igry/mario_kart_world_8011309926",
    )

    assert product is not None
    assert product.price == 5990
    assert product.raw is not None
    assert product.raw["price_evidence"] == "5990"


def test_avito_html_without_semantic_price_does_not_scan_body():
    html = """
<html><body>
  <h1>Mario Kart World Nintendo Switch 2 картридж</h1>
  <div data-marker="item-view/item-description">Полная игра на картридже.</div>
  <section class="similar">Похожие объявления 3 000 ₽</section>
</body></html>
"""
    product = AvitoAdapter().parse_product_details(
        html,
        "https://www.avito.ru/moskva/igry/mario_kart_world_8011309926",
    )

    assert product is not None
    assert product.price is None


def test_avito_html_can_read_product_json_ld_price():
    html = """
<html><head>
  <script type="application/ld+json">
  {"@type":"BreadcrumbList","itemListElement":[{"name":"3 000 ₽"}]}
  </script>
  <script type="application/ld+json">
  {"@type":"Product","name":"Mario Kart World","offers":{"@type":"Offer","price":"5990"}}
  </script>
</head><body><h1>Mario Kart World Nintendo Switch 2 картридж</h1></body></html>
"""
    product = AvitoAdapter().parse_product_details(
        html,
        "https://www.avito.ru/moskva/igry/mario_kart_world_8011309926",
    )

    assert product is not None
    assert product.price == 5990
