from __future__ import annotations

from dataclasses import dataclass, field

from .models import ProductResult
from .normalize import extract_numeric_tokens, token_set


@dataclass
class ProductGroup:
    canonical_title: str
    offers: list[ProductResult] = field(default_factory=list)
    confidence: float = 0.0


def compute_offer_confidence(left: ProductResult, right: ProductResult) -> float:
    left_tokens = token_set(left.title)
    right_tokens = token_set(right.title)
    if not left_tokens or not right_tokens:
        token_score = 0.0
    else:
        inter = len(left_tokens & right_tokens)
        union = len(left_tokens | right_tokens)
        token_score = inter / union if union else 0.0

    left_nums = extract_numeric_tokens(left.title)
    right_nums = extract_numeric_tokens(right.title)
    if not left_nums and not right_nums:
        num_score = 0.0
    else:
        inter = len(left_nums & right_nums)
        union = len(left_nums | right_nums)
        num_score = inter / union if union else 0.0

    confidence = 0.75 * token_score + 0.25 * num_score
    return round(max(0.0, min(1.0, confidence)), 4)


def group_product_results(
    offers: list[ProductResult],
    similarity_threshold: float = 0.45,
) -> list[ProductGroup]:
    groups: list[ProductGroup] = []
    for offer in offers:
        if not groups:
            groups.append(ProductGroup(canonical_title=offer.title, offers=[offer], confidence=1.0))
            continue

        best_group: ProductGroup | None = None
        best_score = -1.0
        for group in groups:
            score = compute_offer_confidence(offer, group.offers[0])
            if score > best_score:
                best_score = score
                best_group = group

        if best_group is not None and best_score >= similarity_threshold:
            best_group.offers.append(offer)
            best_group.confidence = max(best_group.confidence, best_score)
        else:
            groups.append(ProductGroup(canonical_title=offer.title, offers=[offer], confidence=0.0))

    return groups
