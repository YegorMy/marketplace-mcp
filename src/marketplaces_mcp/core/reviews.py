from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

import anyio

from marketplaces_mcp.adapters.base import BaseAdapter
from marketplaces_mcp.core.models import ReviewResult
from marketplaces_mcp.core.normalize import parse_price


_MONTHS = (
    "января|февраля|марта|апреля|мая|июня|июля|августа|"
    "сентября|октября|ноября|декабря"
)
_DATE_RE = rf"\d{{1,2}}\s+(?:{_MONTHS})\s+20\d{{2}}"


def reviews_url(marketplace: str, product_url: str) -> str:
    parsed = urlsplit(product_url)
    path = parsed.path.rstrip("/")
    if marketplace == "ozon":
        path += "/reviews/"
    elif marketplace == "yandex_market":
        path += "/reviews"
    return urlunsplit(("https", parsed.netloc, path, "", ""))


async def fetch_reviews(
    adapter: BaseAdapter,
    product_url: str,
    limit: int,
) -> tuple[list[ReviewResult], list[str], str, int | None, float | None]:
    if adapter.marketplace not in {"ozon", "yandex_market"}:
        return [], ["REVIEWS_UNSUPPORTED"], product_url, None, None
    url = reviews_url(adapter.marketplace, product_url)
    last_warning = "CAMOFOX_FAILED"
    for attempt in range(2):
        try:
            snapshot = await adapter._fetch_with_camofox(url)
        except Exception:
            snapshot = None
        if not snapshot:
            last_warning = "CAMOFOX_FAILED"
        elif adapter._is_blocked(snapshot):
            last_warning = "CAMOFOX_BLOCKED"
        else:
            reviews, total, rating, parse_warnings = parse_reviews(
                adapter.marketplace,
                snapshot,
                limit,
            )
            if reviews:
                warnings = ["CAMOFOX_FALLBACK", "REVIEWS_PARTIAL_SAMPLE", *parse_warnings]
                if attempt:
                    warnings.append("CAMOFOX_RETRIED")
                return reviews, sorted(set(warnings)), url, total, rating
            last_warning = "CAMOFOX_NO_RESULTS"
        if attempt == 0:
            await anyio.sleep(0.5)
    return [], sorted({last_warning, "CAMOFOX_RETRIED"}), url, None, None


def parse_reviews(
    marketplace: str,
    snapshot: str,
    limit: int,
) -> tuple[list[ReviewResult], int | None, float | None, list[str]]:
    if marketplace == "ozon":
        return _parse_ozon(snapshot, limit)
    if marketplace == "yandex_market":
        return _parse_yandex(snapshot, limit)
    return [], None, None, ["REVIEWS_UNSUPPORTED"]


def _parse_ozon(
    text: str,
    limit: int,
) -> tuple[list[ReviewResult], int | None, float | None, list[str]]:
    total_match = re.search(r"Отзывы о товаре\s+(\d[\d\s]*)", text, flags=re.IGNORECASE)
    total = _as_int(total_match.group(1)) if total_match else None
    rating_match = re.search(r"\b([0-5](?:[.,]\d+)?)\s*/\s*5\b", text)
    rating = parse_price(rating_match.group(1)) if rating_match else None
    title_match = re.search(r"Отзывы о товаре\s+\d[\d\s]*\s+([^\"\n]+)", text, flags=re.IGNORECASE)
    variant = title_match.group(1).strip() if title_match else None

    header_re = re.compile(
        rf"^- text: (?P<header>.+?)(?P<date>{_DATE_RE})$",
        flags=re.MULTILINE | re.IGNORECASE,
    )
    headers = list(header_re.finditer(text))
    reviews: list[ReviewResult] = []
    for index, header in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        block = text[header.end() : end]
        body_match = re.search(r"^- text: (?P<body>.+?)(?:\s+Вам помог этот отзыв\?)$", block, flags=re.MULTILINE)
        if not body_match:
            continue
        body = _clean_text(body_match.group("body"))
        if len(body) < 5:
            continue
        before_body = block[: body_match.start()]
        stars = len(re.findall(r"^\s*- img\s*$", before_body, flags=re.MULTILINE))
        author = re.sub(
            rf"\s*(?:изменен\s+)?{_DATE_RE}$",
            "",
            header.group("header"),
            flags=re.IGNORECASE,
        ).strip()
        reviews.append(
            ReviewResult(
                marketplace="ozon",
                author=author or None,
                published_at=header.group("date"),
                rating=float(stars) if 1 <= stars <= 5 else None,
                text=body,
                variant=variant,
                confidence=0.9 if variant else 0.75,
            )
        )
        if len(reviews) >= limit:
            break
    return reviews, total, rating, ["REVIEW_SORT_PLATFORM_DEFAULT"]


def _parse_yandex(
    text: str,
    limit: int,
) -> tuple[list[ReviewResult], int | None, float | None, list[str]]:
    summary_match = re.search(
        r"\b([0-5](?:[.,]\d+)?)\s+\d[\d\s.,KК]*\s+оцен(?:ка|ки|ок)\s+(\d[\d\s]*)\s+отзыв",
        text,
        flags=re.IGNORECASE,
    )
    rating = parse_price(summary_match.group(1)) if summary_match else None
    total = _as_int(summary_match.group(2)) if summary_match else None
    header_re = re.compile(
        rf"^- button \"(?P<author>[^\"]+)\"[^\n]*\n- text: (?P<date>{_DATE_RE})$",
        flags=re.MULTILINE | re.IGNORECASE,
    )
    headers = list(header_re.finditer(text))
    reviews: list[ReviewResult] = []
    for index, header in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        block = text[header.end() : end]
        body_match = re.search(
            r"^- ['\"]?button \"(?P<body>(?:Достоинства:|Недостатки:|Комментарий:).+?)\"['\"]?:?",
            block,
            flags=re.MULTILINE,
        )
        if not body_match:
            continue
        variant_matches = re.findall(
            r"^- text: \"(?P<variant>[^\"]*(?:Размер|Ширина|Длина|Цвет)[^\"]*)\"$",
            block,
            flags=re.MULTILINE,
        )
        variant = variant_matches[-1].strip() if variant_matches else None
        reviews.append(
            ReviewResult(
                marketplace="yandex_market",
                author=header.group("author").strip(),
                published_at=header.group("date"),
                text=_clean_text(body_match.group("body")),
                variant=variant,
                confidence=0.9 if variant else 0.65,
            )
        )
        if len(reviews) >= limit:
            break
    warnings = ["REVIEW_SORT_PLATFORM_DEFAULT"]
    if re.search(r'button "Этот вариант"', text) and not re.search(
        r'button "Этот вариант"[^\n]*\[pressed\]', text
    ):
        warnings.append("REVIEW_VARIANT_FILTER_NOT_CONFIRMED")
    return reviews, total, rating, warnings


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().strip("'\""))


def _as_int(value: str) -> int | None:
    digits = re.sub(r"\D", "", value)
    return int(digits) if digits else None
