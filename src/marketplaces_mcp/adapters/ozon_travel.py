from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import anyio
from bs4 import BeautifulSoup, Tag

from marketplaces_mcp.adapters.base import BaseAdapter
from marketplaces_mcp.core.models import (
    FlightOffer,
    FlightSegment,
    HotelOffer,
    HotelRate,
    ProductResult,
)
from marketplaces_mcp.core.normalize import parse_price

_COMMON_IATA = {
    "москва": "MOW",
    "moscow": "MOW",
    "санкт-петербург": "LED",
    "санкт петербург": "LED",
    "петербург": "LED",
    "spb": "LED",
    "сочи": "AER",
    "адлер": "AER",
    "казань": "KZN",
    "калининград": "KGD",
    "екатеринбург": "SVX",
    "новосибирск": "OVB",
    "минеральные воды": "MRV",
    "самара": "KUF",
    "уфа": "UFA",
    "владивосток": "VVO",
    "хабаровск": "KHV",
    "красноярск": "KJA",
    "мурманск": "MMK",
    "архангельск": "ARH",
    "тбилиси": "TBS",
    "ереван": "EVN",
    "стамбул": "IST",
    "анталья": "AYT",
    "дубай": "DXB",
    "бангкок": "BKK",
}

_AMENITIES = (
    "Wi-Fi",
    "Парковка",
    "Кондиционер",
    "Трансфер",
    "SPA",
    "Сауна",
    "Бассейн",
    "Ресторан",
    "Завтрак",
    "Можно с питомцами",
)

_HOTEL_URL_RE = re.compile(
    r"https?://(?:www\.)?ozon\.ru/travel/hotels/product/[^\s\"'<>]+|"
    r"/travel/hotels/product/[^\s\"'<>]+",
    flags=re.IGNORECASE,
)
_MONEY_RE = re.compile(r"(?:от\s*)?(\d[\d\s\u00a0\u202f.,]*?)\s*₽", flags=re.IGNORECASE)
_TIME_PAIR_RE = re.compile(r"\b((?:[01]\d|2[0-3]):[0-5]\d)\s*[—–-]\s*((?:[01]\d|2[0-3]):[0-5]\d)\b")


class OzonTravelAdapter(BaseAdapter):
    """Read-only parser for public Ozon Travel flight and hotel pages."""

    marketplace = "ozon_travel"
    camofox_wait_seconds = 3.0
    camofox_snapshot_attempts = 6

    def _camofox_snapshot_pending(self, snapshot: str) -> bool:
        if "Получаем расписание рейсов" in snapshot:
            return True
        text = _visible_text(snapshot)
        return "Выберите номер" in text and not _parse_hotel_rates(snapshot, nights=1)

    async def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: str | None = None,
        *,
        adults: int = 1,
        children: int = 0,
        infants: int = 0,
        cabin_class: str = "economy",
        direct_only: bool = False,
        sort: str = "price",
        limit: int = 10,
        strategy: str = "auto",
        fixture_html: str | None = None,
    ) -> tuple[list[FlightOffer], list[str], str]:
        warnings: list[str] = []
        parsed_departure, parsed_return = _validate_flight_request(
            departure_date,
            return_date,
            adults,
            children,
            infants,
            cabin_class,
        )
        if parsed_departure is None:
            return (
                [],
                [parsed_return or "INVALID_DATE"],
                "https://www.ozon.ru/travel/flight/",
            )

        origin_code = await self._resolve_iata(origin, strategy)
        destination_code = await self._resolve_iata(destination, strategy)
        if not origin_code or not destination_code:
            warnings.append("IATA_CODE_REQUIRED")
            source_url = self._flight_landing_url(
                origin, destination, parsed_departure, parsed_return
            )
        else:
            source_url = self.build_flight_url(
                origin_code,
                destination_code,
                parsed_departure,
                parsed_return,
                adults=adults,
                children=children,
                infants=infants,
                cabin_class=cabin_class,
            )

        html, load_warnings = await self._load_travel_page(
            source_url,
            strategy=strategy,
            fixture_html=fixture_html,
            fixture_key=f"flight_{origin}_{destination}_{departure_date}",
        )
        warnings.extend(load_warnings)
        if html:
            offers = self.parse_flight_results(
                html,
                source_url=source_url,
                origin=origin_code or origin,
                destination=destination_code or destination,
                departure_date=parsed_departure,
                return_date=parsed_return,
            )
            if any(not (offer.raw or {}).get("itinerary_verified") for offer in offers):
                warnings.extend(["FLIGHT_ITINERARY_UNVERIFIED", "PRICE_UNVERIFIED"])
            if any(segment.arrival_at is None for offer in offers for segment in offer.segments):
                warnings.append("ARRIVAL_DATE_UNVERIFIED")
            if direct_only:
                offers = [offer for offer in offers if offer.stops == 0]
            offers = _sort_flights(offers, sort)
            if offers:
                return (
                    offers[: _bounded_limit(limit)],
                    sorted(set(warnings)),
                    source_url,
                )

        if strategy == "fixture":
            warnings.append("NO_RESULTS")
            return [], sorted(set(warnings)), source_url

        discovered, discovery_warnings = await self._discover_flight_route(
            origin_code or origin,
            destination_code or destination,
            parsed_departure,
            parsed_return,
            limit=limit,
        )
        warnings.extend(discovery_warnings)
        if not discovered:
            warnings.append("NO_RESULTS")
        return discovered, sorted(set(warnings)), source_url

    async def search_hotels(
        self,
        destination: str,
        check_in: str,
        check_out: str,
        *,
        adults: int = 2,
        rooms: int = 1,
        min_rating: float | None = None,
        stars: list[int] | None = None,
        max_total_price: float | None = None,
        sort: str = "price",
        include_rates: bool = True,
        limit: int = 10,
        strategy: str = "auto",
        fixture_html: str | None = None,
    ) -> tuple[list[HotelOffer], list[str], str]:
        parsed_check_in, parsed_check_out, validation_warning = _validate_hotel_request(
            check_in,
            check_out,
            adults,
            rooms,
        )
        if validation_warning:
            return [], [validation_warning], "https://www.ozon.ru/travel/hotels/"
        assert parsed_check_in is not None and parsed_check_out is not None

        source_url = await self.build_hotel_url(
            destination,
            parsed_check_in,
            parsed_check_out,
            adults=adults,
            rooms=rooms,
            sort=sort,
            strategy=strategy,
        )
        html, warnings = await self._load_travel_page(
            source_url,
            strategy=strategy,
            fixture_html=fixture_html,
            fixture_key=f"hotel_{destination}_{check_in}_{check_out}",
        )
        offers: list[HotelOffer] = []
        if html:
            context_verified, context_warnings, _ = _verify_hotel_context(
                _visible_text(html),
                parsed_check_in,
                parsed_check_out,
                adults,
                rooms,
            )
            warnings.extend(context_warnings)
            offers = self.parse_hotel_results(
                html,
                source_url=source_url,
                destination=destination,
                check_in=parsed_check_in,
                check_out=parsed_check_out,
                context_verified=context_verified,
            )

        if offers and include_rates and strategy != "fixture":
            enriched: list[HotelOffer] = []
            for offer in offers[: min(_bounded_limit(limit), 5)]:
                if offer.total_price is not None and offer.rates:
                    enriched.append(offer)
                    continue
                detail, detail_warnings = await self.hotel_details(
                    offer.url,
                    destination=destination,
                    check_in=check_in,
                    check_out=check_out,
                    adults=adults,
                    rooms=rooms,
                    strategy=strategy,
                )
                warnings.extend(detail_warnings)
                enriched.append(detail or offer)
            offers = enriched + offers[len(enriched) :]

        if not offers and strategy != "fixture":
            offers, discovery_warnings = await self._discover_hotels(
                destination,
                parsed_check_in,
                parsed_check_out,
                limit=limit,
            )
            warnings.extend(discovery_warnings)

        offers = _filter_hotels(offers, min_rating, stars, max_total_price)
        offers = _sort_hotels(offers, sort)
        if not offers:
            warnings.append("NO_RESULTS")
        return offers[: _bounded_limit(limit)], sorted(set(warnings)), source_url

    async def hotel_details(
        self,
        url: str,
        *,
        destination: str,
        check_in: str,
        check_out: str,
        adults: int = 2,
        rooms: int = 1,
        strategy: str = "auto",
        fixture_html: str | None = None,
    ) -> tuple[HotelOffer | None, list[str]]:
        if not _is_ozon_hotel_product_url(url):
            return None, ["UNSUPPORTED_URL"]
        parsed_check_in, parsed_check_out, validation_warning = _validate_hotel_request(
            check_in,
            check_out,
            adults,
            rooms,
        )
        if validation_warning:
            return None, [validation_warning]
        assert parsed_check_in is not None and parsed_check_out is not None
        dated_url = _with_hotel_context_query(
            url,
            parsed_check_in,
            parsed_check_out,
            adults,
            rooms,
            show_all=True,
        )
        html, warnings = await self._load_travel_page(
            dated_url,
            strategy=strategy,
            fixture_html=fixture_html,
            fixture_key=f"hotel_details_{url}",
        )
        if not html:
            return None, warnings
        context_verified, context_warnings, context_evidence = _verify_hotel_context(
            _visible_text(html),
            parsed_check_in,
            parsed_check_out,
            adults,
            rooms,
            allow_single_unit_rate=True,
        )
        warnings.extend(context_warnings)
        result = self.parse_hotel_details(
            html,
            url=dated_url,
            destination=destination,
            check_in=parsed_check_in,
            check_out=parsed_check_out,
            context_verified=context_verified,
            context_evidence=context_evidence,
        )
        if (
            result is not None
            and result.rates
            and context_evidence.get("single_unit_rate_context")
        ):
            warnings = [
                warning
                for warning in warnings
                if warning != "ROOM_COUNT_UNVERIFIED"
            ]
            warnings.append("SINGLE_UNIT_RATE_QUOTE")
        if result is None:
            warnings.append("NO_RESULTS")
        elif context_verified and not result.rates and _MONEY_RE.search(_primary_hotel_text(_visible_text(html))):
            warnings.extend(["ROOM_RATES_UNVERIFIED", "PRICE_UNVERIFIED"])
        return result, sorted(set(warnings))

    def build_flight_url(
        self,
        origin_iata: str,
        destination_iata: str,
        departure_date: date,
        return_date: date | None,
        *,
        adults: int,
        children: int,
        infants: int,
        cabin_class: str,
    ) -> str:
        route = f"{origin_iata.lower()}{destination_iata.lower()}"
        dates = f"d{departure_date.isoformat()}"
        if return_date:
            route += f"{destination_iata.lower()}{origin_iata.lower()}"
            dates += f"d{return_date.isoformat()}"
        return _with_query(
            "https://www.ozon.ru/travel/flight/search",
            {
                "Children": children,
                "Dlts": adults,
                "Infants": infants,
                "ServiceClass": cabin_class.upper(),
                "dates": dates,
                "route": route,
            },
        )

    async def build_hotel_url(
        self,
        destination: str,
        check_in: date,
        check_out: date,
        *,
        adults: int,
        rooms: int,
        sort: str,
        strategy: str,
    ) -> str:
        if _is_ozon_hotel_url(destination):
            base_url = destination
        else:
            base_url = None
            if strategy != "fixture":
                base_url = await self._discover_hotel_destination_url(destination)
            if not base_url:
                base_url = "https://www.ozon.ru/travel/hotels/search-new"
        return _with_hotel_context_query(
            base_url,
            check_in,
            check_out,
            adults,
            rooms,
            query=(
                None
                if base_url != "https://www.ozon.ru/travel/hotels/search-new"
                else destination
            ),
            sorting=_ozon_hotel_sort(sort),
        )

    def parse_flight_results(
        self,
        html: str,
        *,
        source_url: str,
        origin: str,
        destination: str,
        departure_date: date,
        return_date: date | None,
    ) -> list[FlightOffer]:
        text = _visible_text(html)
        offers: list[FlightOffer] = []
        seen: set[tuple] = set()
        for block in _flight_offer_blocks(html, text):
            time_pairs = list(_TIME_PAIR_RE.finditer(block))
            money = list(_MONEY_RE.finditer(block))
            if not time_pairs or not money:
                continue
            # Ozon can show baggage add-ons and an Ozon Card discount before
            # the ordinary public fare. The last currency amount in an offer
            # card is the non-conditional price shown next to "Выбрать".
            price = parse_price(money[-1].group(1))
            journey_dates = [departure_date]
            if return_date is not None:
                journey_dates.append(return_date)
            itinerary_verified = len(time_pairs) == len(journey_dates)
            if not itinerary_verified:
                price = None
            journey_routes = [(origin, destination), (destination, origin)]
            journey_lines = _flight_journey_lines(block)
            segments: list[FlightSegment] = []
            for index, times in enumerate(time_pairs[: len(journey_dates)]):
                journey_text = (
                    journey_lines[index]
                    if index < len(journey_lines)
                    else block
                )
                segment_origin, segment_destination = journey_routes[index]
                segment_date = journey_dates[index]
                segments.append(
                    FlightSegment(
                        origin=segment_origin,
                        destination=segment_destination,
                        departure_at=(
                            f"{segment_date.isoformat()}T{times.group(1)}:00"
                        ),
                        arrival_at=_flight_arrival_at(segment_date, times, block),
                        airline=_parse_airline(journey_text),
                        duration_minutes=_parse_duration_minutes(journey_text),
                        baggage=_extract_baggage(block),
                    )
                )
            airlines = list(
                dict.fromkeys(
                    segment.airline for segment in segments if segment.airline
                )
            )
            baggage = _extract_baggage(block)
            refundable = _bool_from_terms(block, "refund")
            exchangeable = _bool_from_terms(block, "exchange")
            key = (tuple(segment.model_dump_json() for segment in segments),
                   price, baggage, refundable, exchangeable)
            if key in seen:
                continue
            seen.add(key)
            segment_durations = [
                segment.duration_minutes
                for segment in segments
                if segment.duration_minutes is not None
            ]
            duration = sum(segment_durations) if segment_durations else None
            segment_stops = [
                _parse_stops(line) for line in journey_lines[: len(segments)]
            ]
            stops = (
                sum(item for item in segment_stops if item is not None)
                if segment_stops and all(item is not None for item in segment_stops)
                else _parse_stops(block)
            )
            offers.append(
                FlightOffer(
                    url=source_url,
                    origin=origin,
                    destination=destination,
                    departure_date=departure_date,
                    return_date=return_date,
                    price=price,
                    airlines=airlines,
                    segments=segments,
                    stops=stops,
                    duration_minutes=duration,
                    baggage=baggage,
                    refundable=refundable,
                    exchangeable=exchangeable,
                    availability="available" if itinerary_verified else None,
                    confidence=0.82 if itinerary_verified else 0.3,
                    raw={"evidence": block[:2500], "itinerary_verified": itinerary_verified},
                )
            )
        return offers

    def parse_hotel_results(
        self,
        html: str,
        *,
        source_url: str,
        destination: str,
        check_in: date,
        check_out: date,
        context_verified: bool = False,
    ) -> list[HotelOffer]:
        soup = BeautifulSoup(html, "html.parser")
        nights = (check_out - check_in).days
        candidates: list[tuple[str, str, str, str | None]] = []
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "")
            if "/travel/hotels/product/" not in href:
                continue
            url = _canonical_hotel_url(urljoin("https://www.ozon.ru", href))
            card = _smallest_offer_container(anchor)
            title = _clean_title(anchor.get_text(" ", strip=True))
            if not title:
                title = _title_from_url(url)
            text = (
                card.get_text(" ", strip=True)
                if card
                else anchor.get_text(" ", strip=True)
            )
            image = None
            if card:
                image_tag = card.find("img")
                if image_tag:
                    image = (
                        str(image_tag.get("src") or image_tag.get("data-src") or "")
                        or None
                    )
            candidates.append((title, url, text, image))

        if not candidates:
            candidates.extend(_hotel_candidates_from_snapshot(html))

        results: list[HotelOffer] = []
        seen: set[str] = set()
        for title, url, text, image in candidates:
            if not title or not url or url in seen:
                continue
            seen.add(url)
            money = _MONEY_RE.search(text)
            displayed_price = (
                parse_price(money.group(1)) if money and context_verified else None
            )
            is_total = bool(
                re.search(
                    r"(?:за\s+\d+\s+ноч|за\s+проживание|итого)", text, re.IGNORECASE
                )
            )
            total_price = displayed_price if is_total else None
            nightly_price = (
                (total_price / nights) if total_price is not None else displayed_price
            )
            rating, reviews = _parse_rating_and_reviews(text)
            stars = _parse_stars(title, text)
            address, distance = _parse_hotel_location(text, destination)
            amenities = [name for name in _AMENITIES if name.lower() in text.lower()]
            results.append(
                HotelOffer(
                    title=title,
                    url=url,
                    destination=destination,
                    check_in=check_in,
                    check_out=check_out,
                    nights=nights,
                    total_price=total_price,
                    nightly_price=nightly_price,
                    stars=stars,
                    rating=rating,
                    reviews_count=reviews,
                    address=address,
                    distance_to_center=distance,
                    amenities=amenities,
                    availability="available" if displayed_price is not None else None,
                    image_url=image,
                    confidence=0.8 if displayed_price is not None else 0.65,
                    raw={"evidence": text[:3000], "source_url": source_url},
                )
            )
        return results

    def parse_hotel_details(
        self,
        html: str,
        *,
        url: str,
        destination: str,
        check_in: date,
        check_out: date,
        context_verified: bool = False,
        context_evidence: dict[str, Any] | None = None,
    ) -> HotelOffer | None:
        text = _visible_text(html)
        primary_text = _primary_hotel_text(text)
        title = _first_heading(html) or _title_from_url(url)
        if not title:
            return None
        nights = (check_out - check_in).days
        rating, reviews = _parse_rating_and_reviews(primary_text)
        rates = _parse_hotel_rates(html, nights) if context_verified else []
        priced_rates = [rate for rate in rates if rate.price is not None]
        total_price = min(
            (rate.price for rate in priced_rates if rate.price is not None),
            default=None,
        )
        nightly_price = total_price / nights if total_price is not None else None
        address, distance = _parse_hotel_location(primary_text, destination)
        amenities = [
            name for name in _AMENITIES if name.lower() in primary_text.lower()
        ]
        availability = (
            _parse_availability(primary_text, bool(priced_rates))
            if context_verified
            else None
        )
        return HotelOffer(
            title=_clean_title(title),
            url=_canonical_hotel_url(url),
            destination=destination,
            check_in=check_in,
            check_out=check_out,
            nights=nights,
            total_price=total_price,
            nightly_price=nightly_price,
            stars=_parse_stars(title, text),
            rating=rating,
            reviews_count=reviews,
            address=address,
            distance_to_center=distance,
            amenities=amenities,
            rates=rates,
            availability=availability,
            confidence=0.9 if total_price is not None else 0.7,
            raw={
                "evidence": primary_text[:3000],
                "request_context": context_evidence or {},
            },
        )

    async def _load_travel_page(
        self,
        url: str,
        *,
        strategy: str,
        fixture_html: str | None,
        fixture_key: str,
    ) -> tuple[str | None, list[str]]:
        if strategy == "fixture":
            html = (
                fixture_html
                if fixture_html is not None
                else self._read_fixture(fixture_key)
            )
            if html is None:
                return None, ["FIXTURE_NOT_FOUND"]
            if self._is_blocked(html):
                return None, ["CAPTCHA_OR_BLOCKED"]
            return html, []

        html, warnings = await self._load_html(url, url, strategy=strategy)
        if html and not self._is_blocked(html):
            return html, warnings
        if html:
            return None, sorted(set(warnings + ["HIVE_WEB_BLOCKED", "CAPTCHA_OR_BLOCKED"]))
        if "CAPTCHA_OR_BLOCKED" in warnings:
            return None, warnings
        if self.settings.camofox_url:
            try:
                snapshot = await self._fetch_with_camofox(url)
            except Exception:
                snapshot = None
                warnings.append("CAMOFOX_FAILED")
            if snapshot and not self._is_blocked(snapshot):
                warnings.append("CAMOFOX_FALLBACK")
                return snapshot, sorted(set(warnings))
            if snapshot:
                warnings.append("CAMOFOX_BLOCKED")
        else:
            warnings.append("CAMOFOX_NOT_CONFIGURED")
        warnings.append("CAPTCHA_OR_BLOCKED")
        return None, sorted(set(warnings))

    async def _resolve_iata(self, value: str, strategy: str) -> str | None:
        normalized = re.sub(r"\s+", " ", value.strip().lower())
        if re.fullmatch(r"[a-zA-Z]{3}", normalized):
            return normalized.upper()
        if normalized in _COMMON_IATA:
            return _COMMON_IATA[normalized]
        if strategy == "fixture":
            return None
        hits, _ = await self._ddgs(f"site:ozon.ru/travel/flight {value} авиабилеты", 8)
        for hit in hits:
            url = str(hit.get("href") or hit.get("url") or "")
            matches = re.findall(r"-([a-z]{3})(?:/|$)", url.lower())
            if matches:
                return matches[-1].upper()
        return None

    async def _discover_hotel_destination_url(self, destination: str) -> str | None:
        hits, _ = await self._ddgs(
            f"site:ozon.ru/travel/hotels/category {destination} отели", 10
        )
        for hit in hits:
            url = str(hit.get("href") or hit.get("url") or "")
            parsed = urlsplit(url)
            if (
                parsed.netloc.endswith("ozon.ru")
                and "/travel/hotels/category/" in parsed.path
            ):
                return urlunsplit(("https", "www.ozon.ru", parsed.path, "", ""))
        return None

    async def _discover_hotels(
        self,
        destination: str,
        check_in: date,
        check_out: date,
        *,
        limit: int,
    ) -> tuple[list[HotelOffer], list[str]]:
        hits, warning = await self._ddgs(
            f"site:ozon.ru/travel/hotels/product {destination} отель",
            max(_bounded_limit(limit) * 3, 8),
        )
        results: list[HotelOffer] = []
        seen: set[str] = set()
        for hit in hits:
            url = _canonical_hotel_url(str(hit.get("href") or hit.get("url") or ""))
            if "/travel/hotels/product/" not in url or url in seen:
                continue
            title = _clean_title(str(hit.get("title") or "")) or _title_from_url(url)
            if not title:
                continue
            seen.add(url)
            results.append(
                HotelOffer(
                    title=title,
                    url=url,
                    destination=destination,
                    check_in=check_in,
                    check_out=check_out,
                    nights=(check_out - check_in).days,
                    confidence=0.3,
                    raw={
                        "discovery": "public_search_index",
                        "snippet": str(hit.get("body") or "")[:1000],
                    },
                )
            )
            if len(results) >= _bounded_limit(limit):
                break
        warnings = [warning] if warning else []
        if results:
            warnings.extend(
                [
                    "INDEX_DISCOVERY_ONLY",
                    "PRICE_UNVERIFIED",
                    "DATE_AVAILABILITY_UNVERIFIED",
                ]
            )
        else:
            warnings.append("INDEX_DISCOVERY_NO_RESULTS")
        return results, sorted(set(warnings))

    async def _discover_flight_route(
        self,
        origin: str,
        destination: str,
        departure_date: date,
        return_date: date | None,
        *,
        limit: int,
    ) -> tuple[list[FlightOffer], list[str]]:
        hits, warning = await self._ddgs(
            f"site:ozon.ru/travel/flight {origin} {destination} авиабилеты",
            max(_bounded_limit(limit) * 2, 8),
        )
        results: list[FlightOffer] = []
        excluded = False
        for hit in hits:
            raw_url = str(hit.get("href") or hit.get("url") or "")
            try:
                parsed = urlsplit(raw_url)
            except ValueError:
                excluded = True
                continue
            route = re.match(
                r"^/travel/flight/[^/]+-([a-z]{3})/[^/]+-([a-z]{3})(?:/|$)",
                parsed.path, flags=re.IGNORECASE,
            )
            # An indexed city, country or different-airport route cannot prove
            # the requested endpoints. Keep these links price-less even when matched.
            if (parsed.scheme != "https" or parsed.netloc not in {"ozon.ru", "www.ozon.ru"}
                    or route is None
                    or tuple(code.upper() for code in route.groups()) != (origin.upper(), destination.upper())):
                excluded = True
                continue
            results.append(
                FlightOffer(
                    url=urlunsplit(("https", "www.ozon.ru", parsed.path, "", "")),
                    origin=origin,
                    destination=destination,
                    departure_date=departure_date,
                    return_date=return_date,
                    confidence=0.25,
                    raw={
                        "discovery": "public_search_index",
                        "title": str(hit.get("title") or "")[:500],
                        "snippet": str(hit.get("body") or "")[:1000],
                    },
                )
            )
            break
        warnings = [warning] if warning else []
        if excluded:
            warnings.append("INDEX_ROUTE_UNVERIFIED")
        if results:
            warnings.extend(
                [
                    "INDEX_DISCOVERY_ONLY",
                    "PRICE_UNVERIFIED",
                    "DATE_AVAILABILITY_UNVERIFIED",
                ]
            )
        else:
            warnings.append("INDEX_DISCOVERY_NO_RESULTS")
        return results, sorted(set(warnings))

    async def _ddgs(
        self, query: str, max_results: int
    ) -> tuple[list[dict[str, Any]], str | None]:
        try:
            from ddgs import DDGS
        except ImportError:
            return [], "INDEX_DISCOVERY_UNAVAILABLE"

        def run() -> list[dict[str, Any]]:
            with DDGS(timeout=min(self.settings.request_timeout, 15.0)) as client:
                return list(
                    client.text(
                        query,
                        region="ru-ru",
                        safesearch="moderate",
                        max_results=max_results,
                    )
                )

        try:
            return await anyio.to_thread.run_sync(run), None
        except Exception:
            return [], "INDEX_DISCOVERY_FAILED"

    def _flight_landing_url(
        self,
        origin: str,
        destination: str,
        departure_date: date,
        return_date: date | None,
    ) -> str:
        return _with_query(
            "https://www.ozon.ru/travel/flight/",
            {
                "origin": origin,
                "destination": destination,
                "departureDate": departure_date.isoformat(),
                "returnDate": return_date.isoformat() if return_date else None,
            },
        )

    def _proxy_url(self) -> str | None:
        return self.settings.proxy_url_for(
            "ozon_travel"
        ) or self.settings.proxy_url_for("ozon")

    def parse_search_results(self, html: str, query: str) -> list[ProductResult]:
        return []


def _validate_flight_request(
    departure: str,
    returning: str | None,
    adults: int,
    children: int,
    infants: int,
    cabin_class: str,
) -> tuple[date | None, date | str | None]:
    try:
        departure_date = date.fromisoformat(departure)
        return_date = date.fromisoformat(returning) if returning else None
    except ValueError:
        return None, "INVALID_DATE_FORMAT"
    if return_date and return_date < departure_date:
        return None, "RETURN_BEFORE_DEPARTURE"
    if not 1 <= adults <= 9 or not 0 <= children <= 9 or not 0 <= infants <= adults:
        return None, "INVALID_PASSENGER_COUNTS"
    if cabin_class not in {"economy", "comfort", "business", "first"}:
        return None, "INVALID_CABIN_CLASS"
    return departure_date, return_date


def _validate_hotel_request(
    check_in: str,
    check_out: str,
    adults: int,
    rooms: int,
) -> tuple[date | None, date | None, str | None]:
    try:
        parsed_check_in = date.fromisoformat(check_in)
        parsed_check_out = date.fromisoformat(check_out)
    except ValueError:
        return None, None, "INVALID_DATE_FORMAT"
    if parsed_check_out <= parsed_check_in:
        return None, None, "CHECK_OUT_NOT_AFTER_CHECK_IN"
    if not 1 <= adults <= 10 or not 1 <= rooms <= 8 or rooms > adults:
        return None, None, "INVALID_GUEST_COUNTS"
    return parsed_check_in, parsed_check_out, None


def _visible_text(html: str) -> str:
    if re.search(r"^\s*- (?:heading|link|text|article|button)", html, re.MULTILINE):
        lines = []
        for raw in html.splitlines():
            line = re.sub(
                r"^\s*-\s*(?:text|paragraph|heading|link|button|article):?\s*",
                "",
                raw.strip(),
            )
            line = re.sub(r"\s*\[level=\d+\]\s*$", "", line)
            line = line.strip().strip('"')
            if line and not line.startswith("/url:"):
                lines.append(line)
        return "\n".join(lines)
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    return "\n".join(
        part.strip() for part in soup.get_text("\n").splitlines() if part.strip()
    )


def _flight_blocks(text: str) -> list[str]:
    lines = [
        re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()
    ]
    blocks: list[str] = []
    current: list[str] = []
    for line in lines:
        current.append(line)
        if _MONEY_RE.search(line) and any(
            _TIME_PAIR_RE.search(item) for item in current
        ):
            blocks.append(" ".join(current[-12:]))
            current = []
    if (
        current
        and _MONEY_RE.search(" ".join(current))
        and _TIME_PAIR_RE.search(" ".join(current))
    ):
        blocks.append(" ".join(current[-12:]))
    return blocks


def _flight_offer_blocks(source: str, visible_text: str) -> list[str]:
    """Keep one flight card per block when page structure is available."""
    if re.search(r"^\s*- article:\s*$", source, flags=re.MULTILINE):
        blocks = []
        for raw in re.split(r"^\s*- article:\s*$", source, flags=re.MULTILINE)[1:]:
            block = _visible_text(raw)
            if _TIME_PAIR_RE.search(block) and _MONEY_RE.search(block):
                blocks.append(block)
        if blocks:
            return blocks

    soup = BeautifulSoup(source, "html.parser")
    blocks = []
    for article in soup.find_all("article"):
        block = _visible_text(str(article))
        if _TIME_PAIR_RE.search(block) and _MONEY_RE.search(block):
            blocks.append(block)
    return blocks or _flight_blocks(visible_text)


def _parse_airline(block: str) -> str | None:
    journey_line = re.search(r"(?mi)^(.{1,100}?)\s+В пути\b", block)
    if journey_line:
        airline = re.split(
            r",\s*рейс выполняет\b", journey_line.group(1), maxsplit=1, flags=re.IGNORECASE
        )[0].strip(" •|-")
        if airline:
            return airline
    before_time = _TIME_PAIR_RE.split(block, maxsplit=1)[0]
    parts = [
        part.strip(" •|-") for part in re.split(r"[\n•|]", before_time) if part.strip()
    ]
    for part in reversed(parts):
        if len(part) <= 80 and not re.search(
            r"авиа|билет|найден|вариант|отправление", part, re.IGNORECASE
        ):
            return part
    known = re.search(
        r"\b(Победа|Аэрофлот|Россия|S7 Airlines|Smartavia|Utair|Уральские авиалинии|Nordwind|Red Wings|Azimuth)\b",
        block,
        flags=re.IGNORECASE,
    )
    return known.group(1) if known else None


def _flight_arrival_at(departure_date: date, times: re.Match[str], block: str) -> str | None:
    # The displayed day offset is authoritative; clock times alone cannot
    # establish an overnight arrival across different time zones.
    tail = block[times.end():].split("\n", 1)[0]
    offset = re.match(r"\s*\(?\s*([+-]\d{1,2})(?!\d)", tail)
    if offset is None and times.group(2) < times.group(1):
        return None
    try:
        arrival_date = departure_date + timedelta(days=int(offset[1]) if offset else 0)
    except OverflowError:
        return None
    return f"{arrival_date.isoformat()}T{times.group(2)}:00"


def _flight_journey_lines(block: str) -> list[str]:
    """Return one compact source line for each outbound/return journey."""
    return [
        re.sub(r"\s+", " ", line).strip()
        for line in block.splitlines()
        if _TIME_PAIR_RE.search(line) and re.search(r"\bВ пути\b", line)
    ]


def _parse_duration_minutes(text: str) -> int | None:
    match = re.search(
        r"(?:(\d+)\s*ч)?\s*(?:(\d+)\s*м(?:ин)?)", text, flags=re.IGNORECASE
    )
    if not match:
        return None
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    return hours * 60 + minutes


def _parse_stops(text: str) -> int | None:
    if re.search(r"без пересадок|\bпрямой\b", text, flags=re.IGNORECASE):
        return 0
    match = re.search(r"(\d+)\s+пересад", text, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    if re.search(r"пересад", text, flags=re.IGNORECASE):
        return 1
    return None


def _extract_baggage(text: str) -> str | None:
    if re.search(r"без багажа|багаж не включ", text, flags=re.IGNORECASE):
        return "not_included"
    match = re.search(
        r"багаж[^.;|\n]{0,60}?(?=\s+(?:от\s+)?\d[\d\s\u00a0\u202f.,]*\s*₽|$)",
        text,
        flags=re.IGNORECASE,
    )
    return match.group(0).strip() if match else None


def _bool_from_terms(text: str, kind: str) -> bool | None:
    if kind == "refund":
        if re.search(r"невозврат|без возврата", text, flags=re.IGNORECASE):
            return False
        if re.search(r"возврат(?:ный| возможен| включ)", text, flags=re.IGNORECASE):
            return True
    if kind == "exchange":
        if re.search(r"обмен невозмож|без обмена", text, flags=re.IGNORECASE):
            return False
        if re.search(r"обмен возмож|обмен включ", text, flags=re.IGNORECASE):
            return True
    return None


def _smallest_offer_container(anchor: Tag) -> Tag:
    best = anchor
    parent = anchor.parent
    for _ in range(7):
        if not isinstance(parent, Tag) or parent.name in {"body", "html"}:
            break
        text = parent.get_text(" ", strip=True)
        if len(text) > 5000:
            break
        best = parent
        if _MONEY_RE.search(text) and re.search(
            r"отзыв|до центра|Wi-Fi|парков", text, re.IGNORECASE
        ):
            return parent
        parent = parent.parent
    return best


def _hotel_candidates_from_snapshot(
    snapshot: str,
) -> list[tuple[str, str, str, str | None]]:
    candidates: list[tuple[str, str, str, str | None]] = []
    matches = list(_HOTEL_URL_RE.finditer(snapshot))
    for index, match in enumerate(matches):
        start = max(0, match.start() - 500)
        end = min(
            len(snapshot),
            (
                matches[index + 1].start()
                if index + 1 < len(matches)
                else match.end() + 1500
            ),
        )
        block = snapshot[start:end]
        quoted = re.findall(r'(?:link|heading)\s+"([^"]+)"', block, flags=re.IGNORECASE)
        title = _clean_title(quoted[-1] if quoted else "") or _title_from_url(
            match.group(0)
        )
        url = _canonical_hotel_url(urljoin("https://www.ozon.ru", match.group(0)))
        candidates.append((title, url, _visible_text(block), None))
    return candidates


def _hotel_rate_text(source: str) -> str:
    """Preserve room headings and tariff controls in either supported input format."""
    if re.search(r"^\s*- ", source, re.MULTILINE):
        return source
    soup = BeautifulSoup(source, "html.parser")
    for node in soup.select("script,style,noscript"):
        node.decompose()
    for node in soup.select("h1,h2,h3,h4,h5,h6,[role=heading],img,button,[role=button]"):
        if node.parent is None:
            continue
        label = str(node.get("alt") or "") if node.name == "img" else node.get_text(" ", strip=True)
        label = label.replace('"', "'")
        if node.name == "img":
            rendered = f'- img "{label}"'
        elif node.name == "button" or node.get("role") == "button":
            rendered = f'- button "{label}"'
        else:
            level = node.get("aria-level") or (node.name[1:] if node.name.startswith("h") else "2")
            rendered = f'- heading "{label}" [level={level}]'
        node.replace_with("\n" + rendered + "\n")
    return soup.get_text("\n", strip=True)


def _hotel_tariff_blocks(lines: list[str]):
    room_name = None
    pending: list[str] = []
    for line in lines:
        candidate = _room_name_candidate(line)
        other_rate = re.search(r"Другой тариф", line, re.I)
        if candidate or other_rate:
            if room_name and pending:
                yield room_name, pending
            pending = []
            if candidate:
                room_name = candidate
        if room_name:
            pending.append(line)
            if re.match(r'^- (?:button|link) "Выбрать(?: номер| тариф)?"', line, re.I):
                yield room_name, pending
                pending = []
    if room_name and pending:
        yield room_name, pending


def _parse_hotel_rates(source: str, nights: int) -> list[HotelRate]:
    text = _hotel_rate_text(source)
    current_hotel_text = re.split(
        r"Похожие\s+(?:отели|гостиницы|варианты)",
        text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in current_hotel_text.splitlines()
        if line.strip()
        and not re.search(
            r"Ближайшие доступные даты|Ваши даты|Мало подходящих вариантов",
            line,
            re.IGNORECASE,
        )
    ]
    rates: list[HotelRate] = []
    seen: set[tuple] = set()
    for current_room_name, context_lines in _hotel_tariff_blocks(lines):
        prices = [
            parse_price(money.group(1))
            for line in context_lines
            if not re.match(r"^(?:-\s*text:\s*)?\+", line)
            for money in _MONEY_RE.finditer(line)
        ]
        prices = [price for price in prices if price is not None]
        # Without a tariff boundary even equal amounts may be different rates.
        # Do not combine their prices and terms or guess a discount/old-price pair.
        if len(prices) != 1:
            continue
        price = prices[0]
        if price <= 0:
            continue
        context = " ".join(context_lines)
        meal = _first_match(
            context,
            r"(без питания|завтрак(?: включён)?|полупансион|полный пансион)",
        )
        cancellation = _first_match(
            context,
            r"(бесплатная отмена(?:\s+до\s+\d{1,2}\s+[а-яё.]+)?|"
            r"невозврат(?:ный тариф)?)",
        )
        payment = _first_match(
            context, r"(оплата сейчас|оплата в отеле|без предоплаты)"
        )
        availability = _first_match(
            context,
            r"(остал(?:ся|ось|ись)\s+\d+\s+вариант(?:а|ов)?|нет мест)",
        )
        key = (current_room_name, price, meal, cancellation, payment, availability)
        if key in seen:
            continue
        seen.add(key)
        rates.append(
            HotelRate(
                room_name=current_room_name,
                price=price,
                price_per_night=(price / nights)
                if price is not None and nights
                else None,
                meal_plan=meal,
                cancellation_policy=cancellation,
                payment_terms=payment,
                refundable=False
                if cancellation and "невозврат" in cancellation.lower()
                else (True if cancellation else None),
                availability=availability,
            )
        )
        if len(rates) >= 30:
            break
    return rates


def _room_name_candidate(value: str) -> str | None:
    if re.search(r"\[level=1\]\s*$", value):
        return None
    candidate = value.strip().strip('"')
    labelled = re.search(r'(?:heading|img)\s+"([^"\n]+)', candidate, re.IGNORECASE)
    structurally_named = labelled is not None or bool(
        re.match(r"^-\s*text:\s*\+\d+\s+", candidate, re.IGNORECASE)
    )
    if labelled:
        candidate = labelled.group(1).strip()
    else:
        candidate = re.sub(r"^-\s*(?:text:\s*)?", "", candidate).strip()
    candidate = re.sub(r"\s*\[e\d+\](?::)?$", "", candidate).strip(' "')
    candidate = re.sub(r"^\+\d+\s+", "", candidate).strip()
    if (
        not structurally_named
        or not 3 <= len(candidate) <= 180
        or _MONEY_RE.search(candidate)
        or "/url:" in candidate
        or re.search(
            r"выбрать|подробнее|рейтинг|отзыв|ближайшие даты|ваши даты|"
            r"отмен|оплат|питани|завтрак|\bгост(?:ь|я|ей)|\bноч|\bкомнат|"
            r"ванн|кондиционер|wi-fi|показать|начислим|\bмил|услуг|"
            r"\bостал(?:ся|ось|ись)|\bвариант|\bвойти\b|\bрегистрац|"
            r"\bотель\b|\bгостиниц|нет мест|другой тариф|"
            r"\b(?:основн|дополнительн)\w*\s+мест",
            candidate,
            re.IGNORECASE,
        )
        or (
            not structurally_named
            and re.search(r"кроват|саун|спальн|ванн", candidate, re.IGNORECASE)
        )
        or re.fullmatch(r"[+\-]?\s*[\d\s.,]+", candidate)
        or re.fullmatch(r"(?:-\s*)?img|\[e\d+\]:?", candidate)
    ):
        return None
    return candidate


def _first_match(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return match.group(1).strip() if match else None


def _parse_rating_and_reviews(text: str) -> tuple[float | None, int | None]:
    rating = None
    reviews = None
    rating_match = re.search(
        r"(?:рейтинг(?: товара)?[:\s]*)?([1-5][.,]\d)\s*(?:из\s*5\s*)?(?=[\d\s\u00a0\u202f]*отзыв)",
        text,
        flags=re.IGNORECASE,
    )
    if not rating_match:
        rating_match = re.search(
            r"рейтинг(?: товара)?[:\s]*([1-5][.,]\d)", text, flags=re.IGNORECASE
        )
    if rating_match:
        rating = float(rating_match.group(1).replace(",", "."))
    reviews_match = re.search(
        r"(?<![\d.,])(\d(?:[\d\s\u00a0\u202f]*\d)?)\s+отзыв",
        text,
        flags=re.IGNORECASE,
    )
    if reviews_match:
        reviews = int(re.sub(r"\D", "", reviews_match.group(1)))
    return rating, reviews


def _parse_stars(title: str, text: str) -> int | None:
    match = re.search(r"(?:,|\s)([1-5])\s*\*", f"{title} {text}")
    return int(match.group(1)) if match else None


def _parse_hotel_location(text: str, destination: str) -> tuple[str | None, str | None]:
    distance_match = re.search(
        r"(\d+(?:[.,]\d+)?\s*(?:км|м)\s+до\s+центра)", text, flags=re.IGNORECASE
    )
    if not distance_match:
        distance_match = re.search(
            r"(центр(?:а| города)?\s+\d+(?:[.,]\d+)?\s*(?:км|м))",
            text,
            flags=re.IGNORECASE,
        )
    distance = distance_match.group(1) if distance_match else None
    address_match = re.search(
        rf"({re.escape(destination)}[^•|\n]{{0,180}}?)(?:\s*[•|]|\s+\d+(?:[.,]\d+)?\s*(?:км|м)\s+до\s+центра)",
        text,
        flags=re.IGNORECASE,
    )
    address = address_match.group(1).strip(" ,") if address_match else None
    return address, distance


def _parse_availability(text: str, has_prices: bool) -> str | None:
    if has_prices:
        return "available"
    if re.search(r"нет свободных|нет мест", text, flags=re.IGNORECASE):
        return "unavailable"
    sold_out = re.search(r"\bраспродано\b", text, flags=re.IGNORECASE)
    if sold_out and not re.search(
        r"почти(?:\s+всё)?\s*$",
        text[max(0, sold_out.start() - 20) : sold_out.start()],
        flags=re.IGNORECASE,
    ):
        return "unavailable"
    return None


def _primary_hotel_text(text: str) -> str:
    return re.split(
        r"Похожие\s+(?:отели|гостиницы|варианты)|"
        r"Вам может понравиться|Другие варианты|Отели рядом",
        text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]


def _first_heading(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.find("h1")
    if heading:
        return heading.get_text(" ", strip=True)
    match = re.search(r'heading\s+"([^"]+)"\s+\[level=1\]', html, flags=re.IGNORECASE)
    return match.group(1) if match else None


def _clean_title(value: str) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    text = re.sub(r"\s*[|—-]\s*Ozon.*$", "", text, flags=re.IGNORECASE)
    return text


def _title_from_url(url: str) -> str:
    slug = urlsplit(url).path.rstrip("/").split("/")[-1]
    slug = re.sub(r"-\d+$", "", slug)
    return re.sub(r"[-_]+", " ", slug).strip().title()


def _canonical_hotel_url(url: str) -> str:
    parsed = urlsplit(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return urlunsplit(("https", "www.ozon.ru", parsed.path, "", ""))


_RU_MONTHS = {
    1: r"(?:янв\.?|январ(?:я|ь))",
    2: r"(?:февр\.?|феврал(?:я|ь))",
    3: r"(?:мар\.?|март(?:а)?)",
    4: r"(?:апр\.?|апрел(?:я|ь))",
    5: r"ма(?:я|й)",
    6: r"июн(?:\.?|я|ь)",
    7: r"июл(?:\.?|я|ь)",
    8: r"(?:авг\.?|август(?:а)?)",
    9: r"(?:сент\.?|сентябр(?:я|ь))",
    10: r"(?:окт\.?|октябр(?:я|ь))",
    11: r"(?:нояб\.?|ноябр(?:я|ь))",
    12: r"(?:дек\.?|декабр(?:я|ь))",
}


def _verify_hotel_context(
    text: str,
    check_in: date,
    check_out: date,
    adults: int,
    rooms: int,
    *,
    allow_single_unit_rate: bool = False,
) -> tuple[bool, list[str], dict[str, Any]]:
    current_hotel_text = re.split(
        r"Похожие\s+(?:отели|гостиницы|варианты)",
        text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    context = _hotel_context_window(current_hotel_text, check_in, check_out)
    dates_verified = context is not None
    context = context or ""
    guest_counts = {
        int(value)
        for value in re.findall(
            r"(?<!\d)(\d{1,2})\s+гост(?:ь|я|ей)\b",
            context,
            re.IGNORECASE,
        )
    }
    room_context = re.sub(
        r"показать\s+\d{1,2}\s+номер(?:а|ов)?\b",
        "",
        context,
        flags=re.IGNORECASE,
    )
    room_counts = {
        int(value)
        for value in re.findall(
            r"(?<!\d)(\d{1,2})\s+номер(?:а|ов)?\b",
            room_context,
            re.IGNORECASE,
        )
    }
    guests_verified = adults in guest_counts
    rooms_verified = rooms in room_counts
    warnings: list[str] = []
    if not dates_verified:
        warnings.append("DATE_AVAILABILITY_UNVERIFIED")
    if not guests_verified:
        warnings.append("GUEST_COUNT_UNVERIFIED")
    if not rooms_verified:
        warnings.append("ROOM_COUNT_UNVERIFIED")
    single_unit_rate_context = (
        allow_single_unit_rate
        and rooms == 1
        and dates_verified
        and guests_verified
        and not rooms_verified
    )
    verified = dates_verified and guests_verified and (
        rooms_verified or single_unit_rate_context
    )
    if not verified:
        warnings.append("PRICE_UNVERIFIED")
    return (
        verified,
        warnings,
        {
            "dates_verified": dates_verified,
            "guest_count_verified": guests_verified,
            "room_count_verified": rooms_verified,
            "single_unit_rate_context": single_unit_rate_context,
            "rendered_guest_counts": sorted(guest_counts),
            "rendered_room_counts": sorted(room_counts),
            "requested_check_in": check_in.isoformat(),
            "requested_check_out": check_out.isoformat(),
            "requested_adults": adults,
            "requested_rooms": rooms,
        },
    )


def _hotel_context_window(text: str, check_in: date, check_out: date) -> str | None:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    candidates: list[tuple[int, str]] = []
    for width in range(1, min(5, len(lines)) + 1):
        for start in range(0, len(lines) - width + 1):
            date_block = " ".join(lines[start : start + width])
            if not _hotel_dates_match(date_block, check_in, check_out):
                continue
            nearby = " ".join(
                lines[max(0, start - 3) : min(len(lines), start + width + 4)]
            )
            score = 2 if re.search(r"ваши даты", date_block, re.IGNORECASE) else 0
            score += 5 * int(
                bool(re.search(r"\d+\s+гост", nearby, re.IGNORECASE))
            )
            score += int(bool(re.search(r"\d+\s+номер", nearby, re.IGNORECASE)))
            candidates.append((score, nearby))
        if candidates:
            break
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _hotel_dates_match(text: str, check_in: date, check_out: date) -> bool:
    if check_in.isoformat() in text and check_out.isoformat() in text:
        return True
    numeric_in = rf"(?<![\d./-])0?{check_in.day}[./-]0?{check_in.month}(?:[./-]{check_in.year})?(?![\d./-])"
    numeric_out = rf"(?<![\d./-])0?{check_out.day}[./-]0?{check_out.month}(?:[./-]{check_out.year})?(?![\d./-])"
    if re.search(numeric_in, text) and re.search(numeric_out, text):
        return True
    if check_in.month == check_out.month:
        month = _RU_MONTHS[check_in.month]
        same_month_range = re.compile(
            rf"(?<!\d){check_in.day}\s*[—–-]\s*{check_out.day}\s+{month}(?=\s|[,—–-]|$)"
            rf"(?:,?\s+(?P<year>\d{{4}}))?",
            re.IGNORECASE,
        )
        for match in same_month_range.finditer(text):
            if match["year"] is None or int(match["year"]) == check_in.year == check_out.year:
                return True
    def matches_date(value: date) -> bool:
        pattern = (rf"(?<!\d){value.day}\s+{_RU_MONTHS[value.month]}(?=\s|[,—–-]|$)"
                   rf"(?:,?\s+(?P<year>\d{{4}}))?")
        return any(match["year"] is None or int(match["year"]) == value.year
                   for match in re.finditer(pattern, text, re.I))
    return matches_date(check_in) and matches_date(check_out)


def _is_ozon_hotel_url(value: str) -> bool:
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower()
    return (
        parsed.scheme == "https"
        and (host == "ozon.ru" or host.endswith(".ozon.ru"))
        and "/travel/hotels/" in parsed.path
    )


def _is_ozon_hotel_product_url(value: str) -> bool:
    parsed = urlsplit(value)
    return _is_ozon_hotel_url(value) and parsed.path.startswith(
        "/travel/hotels/product/"
    )


def _with_query(url: str, values: dict[str, object | None]) -> str:
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in values.items():
        if value is not None:
            query[key] = str(value)
    return urlunsplit(
        (parsed.scheme or "https", parsed.netloc, parsed.path, urlencode(query), "")
    )


def _with_hotel_context_query(
    url: str,
    check_in: date,
    check_out: date,
    adults: int,
    rooms: int,
    *,
    query: str | None = None,
    sorting: str | None = None,
    show_all: bool | None = None,
) -> str:
    parsed = urlsplit(url)
    replaced = {
        "checkin",
        "checkout",
        "checkindate",
        "checkoutdate",
        "adult",
        "adults",
        "dlts",
        "rooms",
        "room",
        "roomcount",
        "guests",
        "guestcount",
        "showall",
    }
    existing = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if re.sub(r"[^a-z]", "", key.lower()) not in replaced
    ]
    values: list[tuple[str, str]] = existing
    if query is not None:
        values = [(key, value) for key, value in values if key.lower() != "query"]
        values.append(("query", query))
    if sorting is not None:
        values = [(key, value) for key, value in values if key.lower() != "sorting"]
        values.append(("sorting", sorting))
    if show_all is not None:
        values.append(("showAll", str(show_all).lower()))
    values.extend(
        [
            ("checkIn", check_in.isoformat()),
            ("checkOut", check_out.isoformat()),
            ("Dlts", str(adults)),
            ("rooms", str(rooms)),
        ]
    )
    return urlunsplit(
        (parsed.scheme or "https", parsed.netloc, parsed.path, urlencode(values), "")
    )


def _ozon_hotel_sort(value: str) -> str:
    return {
        "price": "lowPrice",
        "price_asc": "lowPrice",
        "price_desc": "highPrice",
        "rating": "rating",
        "popular": "popular",
    }.get(value, "lowPrice")


def _bounded_limit(limit: int) -> int:
    return max(1, min(int(limit), 30))


def _sort_flights(offers: list[FlightOffer], sort: str) -> list[FlightOffer]:
    if sort == "duration":
        return sorted(
            offers,
            key=lambda item: (
                item.duration_minutes is None,
                item.duration_minutes or 0,
                item.price or 0,
            ),
        )
    if sort == "departure":
        return sorted(
            offers,
            key=lambda item: (
                item.segments[0].departure_at
                if item.segments and item.segments[0].departure_at
                else ""
            ),
        )
    return sorted(
        offers,
        key=lambda item: (
            item.price is None,
            item.price or 0,
            item.duration_minutes or 0,
        ),
    )


def _filter_hotels(
    offers: list[HotelOffer],
    min_rating: float | None,
    stars: list[int] | None,
    max_total_price: float | None,
) -> list[HotelOffer]:
    result = offers
    if min_rating is not None:
        result = [
            item
            for item in result
            if item.rating is not None and item.rating >= min_rating
        ]
    if stars:
        allowed = set(stars)
        result = [item for item in result if item.stars in allowed]
    if max_total_price is not None:
        result = [
            item
            for item in result
            if item.total_price is not None and item.total_price <= max_total_price
        ]
    return result


def _sort_hotels(offers: list[HotelOffer], sort: str) -> list[HotelOffer]:
    if sort == "rating":
        return sorted(
            offers,
            key=lambda item: (
                item.rating is None,
                -(item.rating or 0),
                item.total_price or 0,
            ),
        )
    if sort == "price_desc":
        return sorted(
            offers,
            key=lambda item: (item.total_price is None, -(item.total_price or 0)),
        )
    if sort == "popular":
        return sorted(
            offers,
            key=lambda item: (item.reviews_count is None, -(item.reviews_count or 0)),
        )
    return sorted(
        offers,
        key=lambda item: (
            item.total_price is None and item.nightly_price is None,
            item.total_price
            if item.total_price is not None
            else (item.nightly_price or 0) * item.nights,
        ),
    )
