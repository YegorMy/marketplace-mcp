"""Describe conditions attached to observed prices without guessing checkout totals."""
from __future__ import annotations

import re
import math


def price_metadata(text: str, price: float | None) -> dict[str, str | None]:
    if price is None:
        return {"price_kind": "unknown", "price_condition": None}
    conditions = []
    for pattern, label in (
        (r"Ozon\s*Карт|карт\w*\s+Ozon|С банками", "Ozon card / eligible bank payment"),
        (r"карт\w*\s+Яндекс\s*Пэй|₽\s+Пэй", "Yandex Pay card"),
        (r"WB\s*Кошел|кошельк", "WB wallet"),
        (r"промокод", "promo code"),
    ):
        if re.search(pattern, text, re.I):
            conditions.append(label)
    if conditions:
        return {"price_kind": "conditional", "price_condition": "; ".join(conditions)}
    if re.search(r"\bот\s+\d[\d\s.,]*\s*(?:₽|руб)", text, re.I):
        return {"price_kind": "from", "price_condition": "Starting price; exact variant unverified"}
    return {"price_kind": "exact", "price_condition": None}


def primary_snapshot(text: str) -> str:
    """Exclude recommendations from a title-bound product pricing section."""
    heading = re.search(r'^\s*- heading "[^\n]+" \[level=1\]', text, re.M)
    if not heading:
        return ""
    section = text[heading.end():]
    boundary = re.search(
        r'^\s*- (?:heading|text|generic).*?(?:Похожие товары|Рекомендуем также|С этим товаром|Вам может понравиться|Другие товары|Вы смотрели)',
        section, re.M | re.I,
    )
    return section[:boundary.start() if boundary else 6000]


def primary_html_text(soup) -> str:
    title = soup.find("h1")
    if title is None:
        return ""
    fragments = []
    size = 0
    for node in title.find_all_next(string=True):
        if node.parent.name in {"script", "style", "noscript"}:
            continue
        text = str(node).strip()
        if re.search(r"Похожие товары|Рекомендуем также|С этим товаром|Вам может понравиться|Другие товары|Вы смотрели", text, re.I):
            break
        if text:
            fragments.append(text)
            size += len(text)
        if size > 6000:
            break
    return " ".join(fragments)


def is_public_price(product) -> bool:
    return (product.price_kind == "exact" and not product.price_condition
            and product.price is not None and math.isfinite(product.price) and product.price > 0
            and product.availability not in {"removed", "out_of_stock", "unavailable", "sold"})


def price_sort_key(product):
    valid = product.price is not None and math.isfinite(product.price) and product.price > 0
    priority = 0 if is_public_price(product) else {"conditional": 1, "unknown": 2, "from": 3}.get(product.price_kind, 3)
    return (priority if valid else 4, product.price if valid else float("inf"))
