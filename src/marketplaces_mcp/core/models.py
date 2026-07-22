from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class ProductResult(BaseModel):
    marketplace: str
    title: str
    url: str
    price: float | None = None
    old_price: float | None = None
    currency: str = Field(default="RUB")
    rating: float | None = None
    reviews_count: int | None = None
    image_url: str | None = None
    availability: str | None = None
    delivery_hint: str | None = None
    seller: str | None = None
    seller_type: str | None = None
    seller_rating: float | None = None
    seller_reviews_count: int | None = None
    condition: str | None = None
    location: str | None = None
    published_at: str | None = None
    views_count: int | None = None
    delivery_available: bool | None = None
    unit_price: float | None = None
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: float | None = None
    raw: dict[str, Any] | None = None


class SearchResponse(BaseModel):
    query: str
    marketplaces: list[str]
    results: list[ProductResult]
    warnings: list[str] = Field(default_factory=list)
    artifact_id: str | None = None
    tokens_estimate: int | None = None


class ReviewResult(BaseModel):
    marketplace: str
    author: str | None = None
    published_at: str | None = None
    rating: float | None = None
    text: str
    variant: str | None = None
    confidence: float = 0.7


class ReviewsResponse(BaseModel):
    url: str
    marketplace: str
    total_reviews: int | None = None
    rating: float | None = None
    reviews: list[ReviewResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    artifact_id: str | None = None


class OfferGroup(BaseModel):
    canonical_title: str
    offers: list[ProductResult]
    confidence: float = 0.0


class CompareResponse(BaseModel):
    query: str
    groups: list[OfferGroup]
    best_offers: list[ProductResult]
    warnings: list[str] = Field(default_factory=list)
    artifact_id: str | None = None
