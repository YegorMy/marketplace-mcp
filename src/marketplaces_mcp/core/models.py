from __future__ import annotations

from datetime import datetime
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
    unit_price: float | None = None
    scraped_at: datetime = Field(default_factory=datetime.utcnow)
    confidence: float | None = None
    raw: dict[str, Any] | None = None


class SearchResponse(BaseModel):
    query: str
    marketplaces: list[str]
    results: list[ProductResult]
    warnings: list[str] = Field(default_factory=list)
    artifact_id: str | None = None
    tokens_estimate: int | None = None


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
