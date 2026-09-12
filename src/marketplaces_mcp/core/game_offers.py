from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from marketplaces_mcp.core.normalize import token_set


Decision = Literal["qualifies", "rejected", "unknown"]
MediaFormat = Literal[
    "physical_cartridge",
    "game_key_card",
    "digital_code",
    "account_access",
    "service",
    "accessory",
    "empty_case",
    "unknown",
]
CartridgeData = Literal["full_game", "download_required", "unknown"]
Platform = Literal["switch_2", "switch", "both", "unknown"]
PriceKind = Literal["exact", "from_price", "per_item", "multi_item_ambiguous", "unknown"]
TitleMatch = Literal["match", "mismatch", "unknown"]


class GameOfferEvidence(BaseModel):
    field: str
    value: str
    excerpt: str


class GameOfferClassification(BaseModel):
    decision: Decision
    alert_eligible: bool = False
    media_format: MediaFormat = "unknown"
    cartridge_data: CartridgeData = "unknown"
    platform: Platform = "unknown"
    price_kind: PriceKind = "unknown"
    title_match: TitleMatch = "unknown"
    source_verified: bool = False
    allowed_media_formats: list[Literal["physical_cartridge", "game_key_card"]] = Field(
        default_factory=lambda: ["physical_cartridge"]
    )
    require_full_game: bool = False
    reasons: list[str] = Field(default_factory=list)
    evidence: list[GameOfferEvidence] = Field(default_factory=list)


_GAME_WORD = re.compile(r"\b(?:игр(?:а|ы|у|ой|е)|game)\b", re.IGNORECASE)
_GAME_KEY = re.compile(
    r"\b(?:game[\s-]*key\s*card|ключ[\s-]*карт(?:а|ы)|карт(?:а|ридж)[\s-]*ключ)\b",
    re.IGNORECASE,
)
_FULL_DATA = re.compile(
    r"(?:пол(?:ная|ностью)\s+игра\s+на\s+картридже|"
    r"полноценн(?:ый|ая)\s+(?:игровой\s+)?картридж|"
    r"(?:без|не\s+требует)\s+(?:дополнительной\s+)?загрузк|"
    r"full\s+(?:game\s+)?(?:on\s+)?cartridge|no\s+(?:additional\s+)?download\s+required|"
    r"не\s+(?:game[\s-]*key\s*card|ключ[\s-]*карт(?:а|ы)))",
    re.IGNORECASE,
)
_PHYSICAL = re.compile(
    r"\b(?:картридж(?:е|а|ом|и)?|игров(?:ая|ой)\s+карт(?:а|е|у)|"
    r"physical\s+(?:copy|cartridge)|game\s+cartridge|game\s+card)\b",
    re.IGNORECASE,
)
_DIGITAL = re.compile(
    r"\b(?:цифров(?:ой|ая|ую|ые|ого|ых)\s+(?:код|верси(?:я|и|ю|ей)|копи(?:я|и|ю))|"
    r"цифра\b|код\s+(?:активации|загрузки)|"
    r"ключ\s+(?:активации|eshop)|download\s+code|digital\s+(?:code|copy|edition)|"
    r"digital\s+version|e[\s-]*shop\s+(?:code|key))\b",
    re.IGNORECASE,
)
_ACCOUNT = re.compile(
    r"\b(?:аккаунт(?:а|ом|у)?|доступ\s+к\s+(?:аккаунту|профилю)|"
    r"общий\s+(?:аккаунт|профиль)|primary\s+account|secondary\s+account|account\s+access)\b",
    re.IGNORECASE,
)
_SERVICE = re.compile(
    r"\b(?:услуг(?:а|и)|прокат|аренд(?:а|у)|установ(?:ка|лю)|прошив(?:ка|ку)|"
    r"активаци(?:я|ю)|service|rental)\b",
    re.IGNORECASE,
)
_EMPTY_CASE = re.compile(
    r"(?:пуст(?:ая|ой)\s+(?:коробка|бокс|кейс)|коробка\s+без\s+(?:игры|картриджа)|"
    r"без\s+(?:игры|картриджа)\b|empty\s+(?:case|box)|case\s+only|no\s+(?:game|cartridge))",
    re.IGNORECASE,
)
_ACCESSORY = re.compile(
    r"\b(?:чехол|обложка|стикер(?:ы|ов)?|держатель|подставка|защитн(?:ый|ая)\s+кейс|"
    r"protective\s+case|cover\s+only|accessor(?:y|ies))\b",
    re.IGNORECASE,
)
_SWITCH_2 = re.compile(
    r"\b(?:nintendo\s+)?switch\s*2\b|\bns2\b|\bсвитч\s*2\b",
    re.IGNORECASE,
)
_SWITCH_1 = re.compile(
    r"\b(?:nintendo\s+)?switch(?:\s+(?:oled|lite))?\b|\bсвитч(?:\s+(?:oled|lite))?\b",
    re.IGNORECASE,
)
_NOT_SWITCH_2 = re.compile(
    r"(?:не\s+(?:подходит|совместим[аоы]?)\s+(?:для|с)\s+(?:nintendo\s+)?switch\s*2|"
    r"not\s+compatible\s+with\s+(?:nintendo\s+)?switch\s*2|switch\s*1\s+only)",
    re.IGNORECASE,
)
_BOTH = re.compile(
    r"(?:switch\s*(?:/|и|and|&)\s*switch\s*2|"
    r"switch\s*2\s*(?:/|и|and|&)\s*switch|"
    r"совместим[аоы]?\s+с\s+(?:nintendo\s+)?switch\s*2)",
    re.IGNORECASE,
)
_FROM_PRICE = re.compile(r"(?:^|\W)(?:от|from)\s*\d[\d\s]*(?:₽|руб|rub)?", re.IGNORECASE)
_PER_ITEM = re.compile(
    r"(?:цена\s+(?:указана\s+)?за\s+(?:одну|1|шт\.?|игру|картридж)|"
    r"за\s+(?:одну|1)\s+(?:игру|шт\.?|картридж)|per\s+(?:game|item|cartridge)|each)",
    re.IGNORECASE,
)
_MULTI_PRICE = re.compile(
    r"(?:цены?\s+(?:разные|уточняйте|в\s+описании)|кажд(?:ая|ый)\s+по\s+\d|"
    r"несколько\s+(?:игр|картриджей)|игры\s+на\s+выбор|разные\s+(?:игры|картриджи)|"
    r"multiple\s+(?:games|cartridges)|games\s+available|и\s+другие?\s+игр|and\s+other\s+games|"
    r"(?=.*\b(?:игры|картриджи|games|cartridges)\b).*(?:,|/))",
    re.IGNORECASE,
)


def is_game_listing(title: str, description: str | None = None) -> bool:
    """Keep networking hardware and consoles out of automatic game matching."""
    text = _clean(f"{title} {description or ''}")
    if not (_SWITCH_1.search(text) or _SWITCH_2.search(text)):
        return False
    if re.search(r"\b(?:network|router|коммутатор|маршрутизатор|console|консоль|приставка)\b", title, re.I):
        return False
    return bool(
        re.search(r"\b(?:nintendo|cartridge)\b", text, re.I)
        or any(pattern.search(text) for pattern in
               (_GAME_WORD, _PHYSICAL, _GAME_KEY, _DIGITAL, _ACCOUNT, _EMPTY_CASE))
    )


def classify_game_offer(
    title: str,
    description: str | None,
    price: float | None,
    *,
    target_title: str | None = None,
    target_platform: Literal["nintendo_switch_2"] = "nintendo_switch_2",
    source_verified: bool = False,
    allowed_media_formats: tuple[Literal["physical_cartridge", "game_key_card"], ...] = (
        "physical_cartridge",
    ),
    require_full_game: bool = False,
) -> GameOfferClassification:
    """Classify a Switch 2 listing conservatively for cartridge price alerts.

    Missing evidence is never inferred. In particular, a generic ``cartridge``
    claim proves physical media but does not prove that the full game data is on
    the card. Search/index snippets must pass ``source_verified=False``.
    """
    del target_platform  # Reserved for an explicit future platform policy.
    title = _clean(title)
    description = _clean(description or "")
    text = _clean(f"{title} {description}")
    evidence: list[GameOfferEvidence] = []
    reasons: list[str] = []

    media_format, cartridge_data = _classify_media(text, evidence, reasons)
    platform = _classify_platform(text, evidence, reasons)
    price_kind = _classify_price(text, price, evidence, reasons)
    title_match = _classify_title(title, target_title, evidence, reasons)

    accepted_formats = tuple(dict.fromkeys(allowed_media_formats))
    media_accepted = media_format in accepted_formats
    data_accepted = not require_full_game or cartridge_data == "full_game"
    required = (
        media_accepted,
        data_accepted,
        platform in {"switch_2", "both"},
        price_kind == "exact",
        title_match == "match",
        source_verified,
    )
    hard_rejection = (
        media_format in {"digital_code", "account_access", "service", "accessory", "empty_case"}
        or (media_format in {"physical_cartridge", "game_key_card"} and not media_accepted)
        or (require_full_game and cartridge_data == "download_required")
        or platform == "switch"
        or price_kind in {"from_price", "per_item", "multi_item_ambiguous"}
        or (title_match == "mismatch" and media_format != "unknown")
    )
    if all(required):
        decision: Decision = "qualifies"
        alert_eligible = True
        reasons.append("ALL_ALERT_REQUIREMENTS_VERIFIED")
    elif hard_rejection:
        decision = "rejected"
        alert_eligible = False
    else:
        decision = "unknown"
        alert_eligible = False

    if not source_verified:
        reasons.append("DETAIL_SOURCE_NOT_VERIFIED")
    return GameOfferClassification(
        decision=decision,
        alert_eligible=alert_eligible,
        media_format=media_format,
        cartridge_data=cartridge_data,
        platform=platform,
        price_kind=price_kind,
        title_match=title_match,
        source_verified=source_verified,
        allowed_media_formats=list(accepted_formats),
        require_full_game=require_full_game,
        reasons=_dedupe(reasons),
        evidence=evidence,
    )


def _classify_media(
    text: str,
    evidence: list[GameOfferEvidence],
    reasons: list[str],
) -> tuple[MediaFormat, CartridgeData]:
    matches = {
        "game_key_card": _first_non_negated(_GAME_KEY, text),
        "digital_code": _first_non_negated(_DIGITAL, text),
        "account_access": _first_non_negated(_ACCOUNT, text),
        "service": _first_non_negated(_SERVICE, text),
        "empty_case": _EMPTY_CASE.search(text),
        "accessory": _first_non_negated(_ACCESSORY, text),
        "physical_cartridge": _first_non_negated(_PHYSICAL, text),
    }
    exclusion_matches = [name for name in matches if name != "physical_cartridge" and matches[name]]
    if matches["empty_case"]:
        _add_evidence(evidence, "media_format", "empty_case", matches["empty_case"], text)
        reasons.append("MEDIA_EMPTY_CASE")
        return "empty_case", "unknown"
    if len(exclusion_matches) > 1 or (
        exclusion_matches
        and matches["physical_cartridge"]
        and exclusion_matches[0] != "game_key_card"
    ):
        for name in exclusion_matches:
            _add_evidence(evidence, "media_format", name, matches[name], text)
        reasons.append("CONFLICTING_MEDIA_EVIDENCE")
        return "unknown", "unknown"
    if exclusion_matches:
        media = exclusion_matches[0]
        _add_evidence(evidence, "media_format", media, matches[media], text)
        reasons.append(f"MEDIA_{media.upper()}")
        data: CartridgeData = "download_required" if media == "game_key_card" else "unknown"
        return media, data
    if matches["physical_cartridge"]:
        _add_evidence(evidence, "media_format", "physical_cartridge", matches["physical_cartridge"], text)
        full_match = _FULL_DATA.search(text)
        if full_match:
            _add_evidence(evidence, "cartridge_data", "full_game", full_match, text)
            return "physical_cartridge", "full_game"
        reasons.append("CARTRIDGE_DATA_UNVERIFIED")
        return "physical_cartridge", "unknown"
    if _GAME_WORD.search(text):
        reasons.append("MEDIA_FORMAT_UNVERIFIED")
    else:
        reasons.append("NOT_IDENTIFIED_AS_GAME_OFFER")
    return "unknown", "unknown"


def _classify_platform(
    text: str,
    evidence: list[GameOfferEvidence],
    reasons: list[str],
) -> Platform:
    blocked = _NOT_SWITCH_2.search(text)
    if blocked:
        _add_evidence(evidence, "platform", "switch", blocked, text)
        reasons.append("SWITCH_2_INCOMPATIBLE")
        return "switch"
    both = _BOTH.search(text)
    if both:
        _add_evidence(evidence, "platform", "both", both, text)
        return "both"
    switch_2 = _SWITCH_2.search(text)
    if switch_2:
        _add_evidence(evidence, "platform", "switch_2", switch_2, text)
        return "switch_2"
    switch_1 = _SWITCH_1.search(text)
    if switch_1:
        _add_evidence(evidence, "platform", "switch", switch_1, text)
        reasons.append("SWITCH_1_ONLY_OR_UNVERIFIED_FOR_SWITCH_2")
        return "switch"
    reasons.append("PLATFORM_UNVERIFIED")
    return "unknown"


def _classify_price(
    text: str,
    price: float | None,
    evidence: list[GameOfferEvidence],
    reasons: list[str],
) -> PriceKind:
    marker = _FROM_PRICE.search(text)
    if marker:
        _add_evidence(evidence, "price_kind", "from_price", marker, text)
        reasons.append("FROM_PRICE_NOT_ELIGIBLE")
        return "from_price"
    marker = _PER_ITEM.search(text)
    if marker:
        _add_evidence(evidence, "price_kind", "per_item", marker, text)
        reasons.append("PER_ITEM_PRICE_NOT_ELIGIBLE")
        return "per_item"
    marker = _MULTI_PRICE.search(text)
    if marker:
        _add_evidence(evidence, "price_kind", "multi_item_ambiguous", marker, text)
        reasons.append("MULTI_ITEM_PRICE_AMBIGUOUS")
        return "multi_item_ambiguous"
    if price is None or price <= 0:
        reasons.append("EXACT_PRICE_UNVERIFIED")
        return "unknown"
    evidence.append(GameOfferEvidence(field="price_kind", value="exact", excerpt=str(price)))
    return "exact"


def _classify_title(
    listing_title: str,
    target_title: str | None,
    evidence: list[GameOfferEvidence],
    reasons: list[str],
) -> TitleMatch:
    if not target_title or not _clean(target_title):
        reasons.append("TARGET_TITLE_NOT_PROVIDED")
        return "unknown"
    target_tokens = _identity_tokens(target_title)
    listing_tokens = _identity_tokens(listing_title)
    if not target_tokens:
        reasons.append("TARGET_TITLE_HAS_NO_IDENTITY_TOKENS")
        return "unknown"
    missing = sorted(target_tokens - listing_tokens)
    if missing:
        evidence.append(
            GameOfferEvidence(field="title_match", value="mismatch", excerpt="missing: " + ", ".join(missing))
        )
        reasons.append("TARGET_TITLE_MISMATCH")
        return "mismatch"
    evidence.append(GameOfferEvidence(field="title_match", value="match", excerpt=_clean(target_title)))
    return "match"


def _identity_tokens(value: str) -> set[str]:
    generic = {
        "nintendo",
        "switch",
        "cartridge",
        "game",
        "игра",
        "картридж",
        "physical",
        "edition",
        "версия",
    }
    return {token for token in token_set(value) if token not in generic and token != "2"}


def _first_non_negated(pattern: re.Pattern[str], text: str) -> re.Match[str] | None:
    for match in pattern.finditer(text):
        prefix = text[max(0, match.start() - 18) : match.start()].lower()
        if re.search(r"(?:\bне|\bбез|\bnot|\bno)\s*$", prefix):
            continue
        return match
    return None


def _add_evidence(
    evidence: list[GameOfferEvidence],
    field: str,
    value: str,
    match: re.Match[str] | None,
    text: str,
) -> None:
    if match is None:
        return
    start = max(0, match.start() - 45)
    end = min(len(text), match.end() + 45)
    evidence.append(GameOfferEvidence(field=field, value=value, excerpt=text[start:end]))


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("ё", "е").strip()).strip()


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
