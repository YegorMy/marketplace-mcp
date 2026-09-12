from __future__ import annotations

import asyncio
import hashlib
import html
from datetime import date, datetime
from typing import Any
from urllib.parse import urlencode, urljoin, urlsplit

import httpx

from marketplaces_mcp.core.models import TourOffer
from marketplaces_mcp.core.normalize import parse_price


_COUNTRIES = {
    "оаэ": ("ОАЭ", "11"),
    "uae": ("ОАЭ", "11"),
}
_ORIGINS = {
    "санкт-петербург": ("Санкт-Петербург", "3", "piter"),
    "санкт петербург": ("Санкт-Петербург", "3", "piter"),
    "петербург": ("Санкт-Петербург", "3", "piter"),
    "spb": ("Санкт-Петербург", "3", "piter"),
    "led": ("Санкт-Петербург", "3", "piter"),
}


def _int_or_none(value: Any) -> int | None:
    try:
        return int(str(value).strip()) if str(value).strip() else None
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(str(value).strip()) if str(value).strip() else None
    except (TypeError, ValueError):
        return None


class PackageToursAdapter:
    """Independent 1001tur flight+hotel quotes, never an Ozon access diagnosis."""

    provider = "1001tur"

    async def search(
        self,
        *,
        origin: str,
        destination: str,
        departure_date_from: str,
        departure_date_to: str,
        min_nights: int,
        max_nights: int,
        adults: int,
        children: int = 0,
        infants: int = 0,
        child_ages: list[int] | None = None,
        infant_ages: list[int] | None = None,
        rooms: int = 1,
        all_inclusive_only: bool = False,
        stars: list[int] | None = None,
        sort: str = "value",
        limit: int = 30,
    ) -> tuple[list[TourOffer], list[str], str]:
        start = date.fromisoformat(departure_date_from)
        end = date.fromisoformat(departure_date_to)
        if end < start:
            raise ValueError("departure_date_to must not precede departure_date_from")
        if not 1 <= min_nights <= max_nights <= 30:
            raise ValueError("nights must satisfy 1 <= min_nights <= max_nights <= 30")
        if adults < 1 or children < 0 or infants < 0 or children + infants > 4:
            raise ValueError("invalid passenger counts")

        if (end - start).days > 31 or max_nights - min_nights > 11:
            raise ValueError("Use at most a 32-day departure window and 12 stay lengths")
        if rooms != 1:
            raise ValueError("Only one room is quoted; do not multiply into a multi-room total")
        child_ages = child_ages or []
        infant_ages = [0] * infants if infant_ages is None else infant_ages
        if len(child_ages) != children or any(type(a) is not int or not 2 <= a <= 17 for a in child_ages):
            raise ValueError("Provide the exact age (2–17) for every child")
        if len(infant_ages) != infants or any(type(a) is not int or a not in (0, 1) for a in infant_ages):
            raise ValueError("Provide age 0 or 1 for every infant (default 0)")
        if sort not in {"price", "rating", "value"}:
            raise ValueError("Unsupported sort")

        country = _COUNTRIES.get(destination.strip().lower())
        origin_info = _ORIGINS.get(origin.strip().lower())
        if country is None:
            return [], ["PACKAGE_TOURS_DESTINATION_UNSUPPORTED"], "https://www.1001tur.ru/"
        if origin_info is None:
            return [], ["PACKAGE_TOURS_ORIGIN_UNSUPPORTED"], "https://www.1001tur.ru/"

        country_name, country_id = country
        origin_name, origin_id, origin_slug = origin_info
        source_url = f"https://{origin_slug}.1001tur.ru/oae/tury/"
        requested_stars = sorted({s for s in (stars or [4, 5]) if 1 <= int(s) <= 5})
        if not requested_stars:
            requested_stars = [4, 5]

        timeout = httpx.Timeout(45.0, connect=15.0)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/142.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.7",
        }
        offers: list[TourOffer] = []
        warnings: list[str] = [
            "SOURCE_1001TUR_NOT_OZON",
            "SEARCH_RESULTS_PARTIAL",
            "PRICE_REQUIRES_RECONFIRMATION",
            "SINGLE_ROOM_QUOTE",
            "FLIGHT_DETAILS_UNVERIFIED",
            "BAGGAGE_UNVERIFIED",
            "TRANSFER_UNVERIFIED",
        ]
        if infants:
            warnings.append("INFANT_AGE_BUCKET_UNDER_2")
        async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
            semaphore = asyncio.Semaphore(2)

            async def one(nights: int):
                async with semaphore:
                    return await self._search_one(
                        client,
                        country_name=country_name,
                        country_id=country_id,
                        origin_name=origin_name,
                        origin_id=origin_id,
                        start=start,
                        end=end,
                        nights=nights,
                        adults=adults,
                        children=children,
                        infants=infants,
                        kid_ages=[max(1, age) for age in infant_ages] + child_ages,
                        all_inclusive_only=all_inclusive_only,
                        stars=requested_stars,
                    )

            tasks = [asyncio.create_task(one(nights)) for nights in range(min_nights, max_nights + 1)]
            try:
                done, pending = await asyncio.wait(tasks, timeout=90)
                batches = [task.exception() if task.exception() else task.result() for task in tasks if task in done]
                if pending:
                    warnings.append("PACKAGE_TOURS_TIMEOUT_PARTIAL")
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

        for batch in batches:
            if isinstance(batch, Exception):
                warnings.append(f"PACKAGE_TOURS_DURATION_FAILED_{type(batch).__name__}")
            else:
                batch_offers, batch_warnings = batch
                offers.extend(batch_offers)
                warnings.extend(batch_warnings)

        deduped: dict[tuple, TourOffer] = {}
        for offer in offers:
            key = (
                offer.hotel_name.casefold(),
                offer.departure_date,
                offer.nights,
                offer.total_price,
                offer.operator_name, offer.room, offer.meal_plan, offer.url,
            )
            deduped.setdefault(key, offer)
        offers = list(deduped.values())
        if sort == "price":
            offers.sort(key=lambda item: (item.total_price, -item.nights, item.hotel_name))
        elif sort == "rating":
            offers.sort(key=lambda item: (-(item.rating or 0), item.price_per_night, item.hotel_name))
        else:
            offers.sort(key=lambda item: (item.price_per_night, item.total_price, -item.nights))
        if not offers:
            warnings.append("NO_VERIFIED_RESULTS")
        return offers[: max(1, min(int(limit), 100))], sorted(set(warnings)), source_url

    async def _search_one(
        self,
        client: httpx.AsyncClient,
        *,
        country_name: str,
        country_id: str,
        origin_name: str,
        origin_id: str,
        start: date,
        end: date,
        nights: int,
        adults: int,
        children: int,
        infants: int,
        kid_ages: list[int],
        all_inclusive_only: bool,
        stars: list[int],
    ) -> tuple[list[TourOffer], list[str]]:
        date_range = f"{start:%d.%m.%Y} - {end:%d.%m.%Y}"
        form: list[tuple[str, str]] = [
            ("destination", country_name),
            ("destination_id", country_id),
            ("Country", country_id),
            ("Curort", ""),
            ("Hotel", ""),
            ("dateRange", date_range),
            ("NightOt", str(nights)),
            ("NightDo", str(nights)),
            ("adults", str(adults)),
            ("kids", str(len(kid_ages))),
            ("ticket_include", "1"),
            ("flight_type", "any"),
        ]
        form.extend(("kidsAge", str(age)) for age in kid_ages)
        form.extend(("Kat", str(star)) for star in stars)
        if all_inclusive_only:
            form.append(("Food", "1"))
        form.append(("from_city", origin_id))
        date_fields = [
            ("dates", date_range),
            ("SDay", f"{start:%d}"),
            ("SMonth", f"{start:%m}"),
            ("SYear", f"{start:%Y}"),
            ("EDay", f"{end:%d}"),
            ("EMonth", f"{end:%m}"),
            ("EYear", f"{end:%Y}"),
        ]
        digest = hashlib.md5(urlencode(form + date_fields).encode()).hexdigest()
        params: list[tuple[str, str]] = [
            ("sortByCheapestHotels", "1"),
            ("json", "1"),
            *form,
            ("act", "search"),
            ("md5_hash", digest),
            ("firstPage", "1"),
            ("pageType", "main"),
            ("pageTypeNew", "inner"),
            ("simpleSearch", "1"),
            *date_fields,
            ("getSearchId", "1"),
        ]
        query_url = "https://www.1001tur.ru/search/ajax/?" + urlencode(params)
        response = await client.get(query_url)
        response.raise_for_status()
        payload = response.json()
        warnings = []
        offers = []
        for attempt in range(4):
            if not isinstance(payload, dict) or payload.get("status") not in ("yes", None):
                return [], ["PACKAGE_TOURS_RESPONSE_UNVERIFIED"]
            if isinstance(payload.get("tourlist"), list) and payload["tourlist"]:
                break
            if not payload.get("search_id") or not payload.get("session"):
                return [], ["PACKAGE_TOURS_RESPONSE_UNVERIFIED"]
            if attempt == 3:
                warnings.append("PACKAGE_TOURS_SEARCH_PENDING")
                break
            await asyncio.sleep(5)
            response = await client.get("https://www.1001tur.ru/search/ajax/", params={
                "page": "1", "sortByCheapestHotels": "1", "json": "1", "md5_hash": digest,
                "session": payload["session"], "search_id": payload["search_id"],
            })
            response.raise_for_status()
            payload = response.json()
        raw_tours = payload.get("tourlist") or []
        if not isinstance(raw_tours, list):
            return [], ["PACKAGE_TOURS_RESPONSE_UNVERIFIED"]
        for parent in raw_tours:
            if not isinstance(parent, dict):
                continue
            candidates = [parent] + [r for r in (parent.get("tour_by_hotel") or []) if isinstance(r, dict)]
            for raw in candidates:
                try:
                    offer = self._parse_offer(raw, origin_name=origin_name)
                    echoed_ages = sorted(int(a) for a in raw.get("kidsAge", []))
                    matches = (
                        offer is not None and offer.flight_included is True
                        and str(raw.get("Country")) == country_id
                        and str(raw.get("fromcity_id")) == origin_id
                        and start <= offer.departure_date <= end and offer.nights == nights
                        and (offer.adults, offer.children, offer.infants) == (adults, children, infants)
                        and echoed_ages == sorted(kid_ages)
                        and offer.currency == "RUB" and offer.stars in stars
                        and raw.get("hotel_stop") == "N"
                        and (not all_inclusive_only or str(raw.get("food_name_ruspo", "")).upper() in {"AI", "UAI", "UAL", "ALL", "SAI"}
                             or str(raw.get("food_name", "")).strip().lower() in {"всё включено", "все включено", "ультра всё включено", "ультра все включено"})
                    )
                except (TypeError, ValueError, KeyError, OverflowError):
                    matches = False
                if matches:
                    offers.append(offer)
                else:
                    warnings.append("UNVERIFIED_OR_MISMATCHED_OFFERS_EXCLUDED")
        return offers, sorted(set(warnings))

    def _parse_offer(self, raw: dict[str, Any], *, origin_name: str) -> TourOffer | None:
        price_text = html.unescape(str(raw.get("price_all") or raw.get("SupplierPriceRub") or ""))
        price = parse_price(price_text)
        import math
        if price is not None and not math.isfinite(price):
            return None
        nights = int(raw.get("hotelNights") or raw.get("Night") or 0)
        hotel_name = str(raw.get("hotel_name") or "").strip()
        departure_raw = str(raw.get("sd_s_full") or raw.get("date") or "")
        if price is None or price <= 0 or nights <= 0 or not hotel_name or not departure_raw:
            return None
        departure = (
            date.fromisoformat(departure_raw)
            if "-" in departure_raw
            else datetime.strptime(departure_raw, "%d.%m.%Y").date()
        )
        details: dict[str, Any] = raw.get("dop_info_hotel") or {}
        destination = str(raw.get("tour_place") or raw.get("tour_place_country") or "ОАЭ")
        tour_url = urljoin("https://www.1001tur.ru/", str(raw.get("tour") or raw.get("fullUrl") or ""))
        if urlsplit(tour_url).hostname != "www.1001tur.ru" or not urlsplit(tour_url).path.startswith("/tourdesc/"):
            return None
        image_url = urljoin("https:", str(raw.get("hotel_img") or "")) if raw.get("hotel_img") else None
        infants = int(raw.get("infants") or 0)
        total_children = int(raw.get("kids") or 0)
        return TourOffer(
            provider=self.provider,
            url=tour_url,
            hotel_name=hotel_name,
            destination=destination,
            departure_from=str(raw.get("departure_from") or origin_name),
            departure_date=departure,
            return_date=(datetime.strptime(raw["sd_e_full"], "%d.%m.%Y").date() if raw.get("sd_e_full") else None),
            nights=nights,
            total_price=float(price),
            price_per_night=round(float(price) / nights, 2),
            currency=str(raw.get("currency") or "RUB"),
            stars=_int_or_none(raw.get("hotel_cat")),
            rating=_float_or_none(details.get("rate")),
            reviews_count=_int_or_none(details.get("reviews")),
            meal_plan=str(raw.get("food_name") or "") or None,
            room=str(raw.get("room") or raw.get("NTip") or "") or None,
            adults=int(raw.get("adults") or 0),
            children=max(total_children - infants, 0),
            infants=infants,
            operator_name=str(raw.get("operator_name") or "") or None,
            beach_line=str(details.get("beachLine") or "") or None,
            beach_distance_m=_int_or_none(details.get("dist_to_beach")),
            beach_type=str(details.get("beachTypeName") or "") or None,
            flight_included=(str(raw.get("ticket_include")) == "1" if str(raw.get("ticket_include")) in {"0", "1"} else None),
            transfer_included=None,
            baggage=None,
            availability="quoted_not_booked" if raw.get("hotel_stop") == "N" else None,
            image_url=image_url,
            confidence=0.65,
            raw={
                "source": "1001tur_public_package_feed",
                "requested_party": raw.get("hotel_place"),
                "operator_id": raw.get("operator_id"),
                "ticket_include": raw.get("ticket_include"),
                "provider_child_age_buckets": raw.get("kidsAge"),
                "flight_type": raw.get("flightType"),
                "tour_id": raw.get("md5"),
            },
        )
