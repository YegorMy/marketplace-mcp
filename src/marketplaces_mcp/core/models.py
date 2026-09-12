from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ProductResult(BaseModel):
    marketplace: str
    title: str
    url: str
    price: float | None = None
    price_kind: str = "unknown"
    price_condition: str | None = None
    game_offer: dict[str, Any] | None = None
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

    @model_validator(mode="after")
    def classify_game_media(self):
        import re
        if self.game_offer is None and re.search(r"switch|свитч|свич|\bns2\b", self.title, re.I):
            from marketplaces_mcp.core.game_offers import classify_game_offer, is_game_listing
            raw = self.raw or {}
            description = raw.get("description") or raw.get("card_text")
            if is_game_listing(self.title, description):
                self.game_offer = classify_game_offer(
                    self.title, description, self.price,
                ).model_dump()
        if self.game_offer and self.price_kind != "exact":
            self.game_offer["price_kind"] = "from_price" if self.price_kind == "from" else "unknown"
            if self.price_condition:
                self.game_offer["price_condition"] = self.price_condition
            self.game_offer["alert_eligible"] = False
        return self


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


class FlightSegment(BaseModel):
    origin: str | None = None
    destination: str | None = None
    departure_at: str | None = None
    arrival_at: str | None = None
    airline: str | None = None
    flight_number: str | None = None
    duration_minutes: int | None = None
    cabin_class: str | None = None
    baggage: str | None = None


class FlightOffer(BaseModel):
    provider: str = "ozon_travel"
    url: str
    origin: str
    destination: str
    departure_date: date
    return_date: date | None = None
    price: float | None = None
    currency: str = "RUB"
    airlines: list[str] = Field(default_factory=list)
    segments: list[FlightSegment] = Field(default_factory=list)
    stops: int | None = None
    duration_minutes: int | None = None
    baggage: str | None = None
    refundable: bool | None = None
    exchangeable: bool | None = None
    availability: str | None = None
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: float | None = None
    raw: dict[str, Any] | None = None


class FlightSearchResponse(BaseModel):
    origin: str
    destination: str
    departure_date: date | None = None
    return_date: date | None = None
    adults: int = 1
    children: int = 0
    infants: int = 0
    cabin_class: str = "economy"
    results: list[FlightOffer] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_url: str
    artifact_id: str | None = None


class HotelRate(BaseModel):
    room_name: str | None = None
    price: float | None = None
    price_per_night: float | None = None
    currency: str = "RUB"
    meal_plan: str | None = None
    cancellation_policy: str | None = None
    payment_terms: str | None = None
    refundable: bool | None = None
    availability: str | None = None


class HotelOffer(BaseModel):
    provider: str = "ozon_travel"
    title: str
    url: str
    destination: str
    check_in: date
    check_out: date
    nights: int
    total_price: float | None = None
    nightly_price: float | None = None
    currency: str = "RUB"
    stars: int | None = None
    rating: float | None = None
    reviews_count: int | None = None
    address: str | None = None
    distance_to_center: str | None = None
    amenities: list[str] = Field(default_factory=list)
    rates: list[HotelRate] = Field(default_factory=list)
    availability: str | None = None
    image_url: str | None = None
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: float | None = None
    raw: dict[str, Any] | None = None


class HotelSearchResponse(BaseModel):
    destination: str
    check_in: date | None = None
    check_out: date | None = None
    nights: int | None = None
    adults: int = 2
    rooms: int = 1
    results: list[HotelOffer] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_url: str
    artifact_id: str | None = None


class TourOffer(BaseModel):
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    price_status: str = "live_quote_not_final_booking"
    rooms: int = 1
    provider: str
    url: str
    hotel_name: str
    destination: str
    departure_from: str
    departure_date: date
    return_date: date | None = None
    nights: int
    total_price: float
    price_per_night: float
    currency: str = "RUB"
    stars: int | None = None
    rating: float | None = None
    reviews_count: int | None = None
    meal_plan: str | None = None
    room: str | None = None
    adults: int = 2
    children: int = 0
    infants: int = 0
    operator_name: str | None = None
    beach_line: str | None = None
    beach_distance_m: int | None = None
    beach_type: str | None = None
    flight_included: bool | None = None
    transfer_included: bool | None = None
    baggage: str | None = None
    availability: str | None = None
    image_url: str | None = None
    confidence: float = 0.8
    raw: dict[str, Any] | None = None


class TourSearchResponse(BaseModel):
    child_ages: list[int] = Field(default_factory=list)
    infant_ages: list[int] = Field(default_factory=list)
    rooms: int = 1
    requested_provider: str = "1001tur"
    origin: str
    destination: str
    departure_date_from: date
    departure_date_to: date
    min_nights: int
    max_nights: int
    adults: int
    children: int = 0
    infants: int = 0
    meal_plan: str | None = None
    results: list[TourOffer] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_url: str
    artifact_id: str | None = None


class OzonTourLead(BaseModel):
    hotel_name: str
    source_url: str
    total_price: None = None
    meal_plan: None = None
    evidence: str
    warning: str


class OzonTourRate(BaseModel):
    provider: Literal["ozon_travel"] = "ozon_travel"
    hotel_name: str
    room_name: str
    meal_plan: str
    operator: str | None = None
    departure_date: date
    stay_end_date: date
    return_date: None = None
    nights: int = Field(ge=1)
    adults: int = Field(ge=1)
    child_ages: list[int] = Field(default_factory=list)
    rooms: Literal[1] = 1
    total_price: float = Field(gt=0)
    currency: Literal["RUB"] = "RUB"
    price_per_night: float = Field(gt=0)
    flight_included: Literal[True] = True
    flight_selection_pending: Literal[True] = True
    baggage: None = None
    transfer: None = None
    availability: Literal["quoted_not_booked"] = "quoted_not_booked"
    source_url: str
    evidence: str


class OzonTourResponse(BaseModel):
    provider: Literal["ozon_travel"] = "ozon_travel"
    source_url: str
    checked_at: float = Field(default_factory=lambda: datetime.now(timezone.utc).timestamp())
    offers: list[OzonTourLead | OzonTourRate] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    access: dict[str, Any] | None = None
    browser_tab_id: str | None = None
    note: str | None = None
