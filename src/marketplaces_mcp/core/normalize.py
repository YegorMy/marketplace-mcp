from __future__ import annotations

import re
import math


def normalize_title(value: object) -> str:
    text = "" if value is None else str(value)
    text = text.lower()
    text = text.replace("ё", "е")
    text = re.sub(r"(\d+)([a-zа-я]+)", r"\1 \2", text)
    text = re.sub(r"([a-zа-я]+)(\d+)", r"\1 \2", text)
    text = text.replace("черный", "black").replace("черная", "black").replace("черное", "black")
    text = re.sub(r"[^\wа-яА-Яa-zA-Z\d\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


_PRICE_RE = re.compile(r"\d[\d.,]*\d|\d")


def parse_price(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    normalized = re.sub(r"[\s\u00a0\u2000-\u200f\u202f\u205f\u3000]", "", text)
    match = _PRICE_RE.search(normalized)
    if not match:
        return None

    raw = match.group(0)
    raw = raw.replace("\u00A0", "")
    if "," in raw and "." in raw:
        last_dot = raw.rfind(".")
        last_comma = raw.rfind(",")
        if last_comma > last_dot:
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    else:
        raw = raw.replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


_STOPWORDS = {
    "без", "new", "new!", "the", "and", "or", "и",
    "за", "для", "from", "with", "без", "на", "в", "для", "по", "от", "до",
}


def token_set(value: str) -> set[str]:
    norm = normalize_title(value)
    tokens = [t for t in norm.split() if t and t not in _STOPWORDS and len(t) > 1]
    return set(tokens)


def extract_numeric_tokens(value: str) -> set[str]:
    if not value:
        return set()
    matches = re.findall(r"\d+(?:[.,]\d+)?", str(value))
    result = set()
    for m in matches:
        if m:
            key = _canonical_number(m)
            if key:
                result.add(key)
    return result


def _canonical_number(raw: str) -> str:
    normalized = re.sub(r"[\s\u00a0\u2000-\u200f\u202f\u205f\u3000]", "", raw).replace(",", ".")
    if normalized.count(".") > 1:
        parts = normalized.split(".")
        normalized = "".join(parts[:-1]) + "." + parts[-1]
    if not normalized:
        return ""
    try:
        value = float(normalized)
    except ValueError:
        return ""
    if math.isclose(value, round(value)):
        return str(int(round(value)))
    return normalized.rstrip("0").rstrip(".")
