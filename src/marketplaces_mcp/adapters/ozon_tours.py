"""Ozon package-tour search and room-rate evidence from its public browser UI."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import date, timedelta
import fcntl
import json
import os
import re
import time
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from bs4 import BeautifulSoup

from marketplaces_mcp.core.ozon_tours_browser import OzonToursBrowser, USER_ID, _PAGE_EVIDENCE

SEARCH = "https://www.ozon.ru/travel/tours/search"
MEALS = {"ozon_ai": "Всё включено", "ozon_sai": "Всё включено с ограничениями",
         "ozon_aip": "Премиум всё включено", "ozon_uai": "Ультра всё включено"}
_CAPTURE = """(() => ({url:location.href,
 inputs:Array.from(document.querySelectorAll('[data-widget=searchFormDesktop] input')).map(x=>({name:x.name,value:x.value})),
 html:(document.querySelector('[data-widget=toursSearchResult]')||{}).outerHTML||'',
 detail:(document.querySelector('[data-widget=toursRoomsListDesktop]')||{}).outerHTML||'',
 hotel:(document.querySelector('[data-widget=hotelsPageHeader] h2')||document.querySelector('h2')||{}).innerText||'',
 loading:/Ищем лучшие|Получаем выгодные/.test((document.querySelector('[data-widget=toursSearchResult]')||{}).innerText||''),
 text:document.body.innerText.slice(0,2000)
}))()"""


def build_search_url(origin="LED", destination="ОАЭ", departure_date="", min_nights=5,
                     max_nights=9, adults=2, child_ages=None, rooms=1, all_inclusive_only=True):
    if origin.casefold().strip() not in {"led", "санкт-петербург", "санкт петербург"}:
        raise ValueError("Only Saint Petersburg is currently verified")
    if destination.casefold().strip() not in {"оаэ", "uae", "united arab emirates"}:
        raise ValueError("Only UAE is currently verified")
    date.fromisoformat(departure_date)
    if not 2 <= min_nights <= max_nights <= 21 or max_nights - min_nights > 4:
        raise ValueError("Use at most five stay lengths per call, e.g. 5–9 and 10–12")
    ages = list(child_ages or [])
    if rooms != 1 or not 1 <= adults <= 6 or len(ages) > 3:
        raise ValueError("One room, 1–6 adults and at most three children are supported")
    if any(type(age) is not int or not 0 <= age <= 16 for age in ages):
        raise ValueError("Exact ages at trip end are required (0 means under one year)")
    params = dict(Dlts=adults, fromCity="140212000", toCountry="210915000",
                  startDate=departure_date, minNight=min_nights, maxNight=max_nights)
    if ages:
        params["Children"] = ",".join(map(str, ages))
    if all_inclusive_only:
        params["mealTypes"] = ",".join(sorted(MEALS))
    return SEARCH + "?" + urlencode(params)


def search_context(url):
    u = urlsplit(url)
    if u.scheme != "https" or u.hostname != "www.ozon.ru" or u.path.rstrip("/") != "/travel/tours/search":
        raise ValueError("Expected an Ozon package search URL")
    raw = parse_qs(u.query)
    keys = ("Dlts", "Children", "fromCity", "toCountry", "startDate", "minNight", "maxNight", "mealTypes")
    if any(len(raw.get(k, [])) > 1 for k in keys):
        raise ValueError("Ambiguous search context")
    result = {k: raw[k][0] for k in keys if k in raw}
    for k in ("Children", "mealTypes"):
        if k in result:
            result[k] = ",".join(sorted(result[k].split(",")))
    return result


def parse_leads(data, expected_url, limit=10):
    if search_context(data.get("url", "")) != search_context(expected_url):
        raise ValueError("Ozon changed the requested search context")
    # The broad card price can still be breakfast even with AI filters selected.
    soup = BeautifulSoup(data.get("html", ""), "html.parser")
    leads = []
    for card in soup.select('[data-widget=toursSearchResult] [gallerytrackinginfo]'):
        name = card.select_one("span.tsBodyControl500Medium")
        if not name:
            continue
        leads.append({"hotel_name": name.get_text(" ", strip=True), "source_url": expected_url,
                      "total_price": None, "meal_plan": None,
                      "evidence": card.get_text(" ", strip=True)[:1200],
                      "warning": "CARD_PRICE_MAY_USE_A_DIFFERENT_MEAL_PLAN; call ozon_travel_tour_details"})
        if len(leads) >= limit:
            break
    return leads


def parse_rates(data, expected_url, hotel_name, all_inclusive_only=True, limit=20):
    u = urlsplit(data.get("url", ""))
    if u.scheme != "https" or u.hostname != "www.ozon.ru" or u.path != "/travel/tours/hotel":
        raise ValueError("Expected Ozon package room-selection page")
    query = parse_qs(u.query)
    context = search_context(expected_url)
    nested = query.get("searchRawQuery", [])
    if len(nested) != 1 or search_context(SEARCH + "?" + nested[0]) != context:
        raise ValueError("Room page belongs to a different trip")
    if data.get("hotel", "").strip() != hotel_name:
        raise ValueError("Hotel identity differs")
    start = date.fromisoformat(context["startDate"])
    if query.get("date") != [start.isoformat()]:
        raise ValueError("Selected departure date differs")
    soup = BeautifulSoup(data.get("detail", ""), "html.parser")
    root = soup.select_one('[data-widget=toursRoomsListDesktop]')
    if not root:
        return []
    offers = []
    for room in root.select("div.travel_ef3_7"):
        room_title = room.select_one("span.tsHeadline500Medium")
        if not room_title:
            continue
        # Each meal heading directly owns one list of priced operator rows.
        for heading in room.select("span.tsBodyControl400Small"):
            meal = heading.get_text(" ", strip=True)
            if all_inclusive_only and meal not in MEALS.values():
                continue
            group = heading.parent.parent
            for button in group.find_all("button"):
                if button.get_text(" ", strip=True) != "Выбрать":
                    continue
                row = button.parent
                text = row.get_text(" ", strip=True)
                if not re.search(r"тур с\s+перел[её]том", text, re.I):
                    continue
                nights = re.search(r"(\d+) ноч", text)
                end = re.search(r"до (\d{2})\.(\d{2})", text)
                prices = re.findall(r"(\d[\d\s\u00a0\u202f]*)\s*₽", text)
                if not nights or not end or len(prices) != 1:
                    continue
                n = int(nights[1])
                if not int(context["minNight"]) <= n <= int(context["maxNight"]):
                    continue
                finish = start + timedelta(days=n)
                if (finish.day, finish.month) != (int(end[1]), int(end[2])):
                    continue
                price = int(re.sub(r"\s", "", prices[0]))
                if price <= 0:
                    continue
                operator_nodes = row.select("span.tsBody300XSmall")
                operator = next((x.get_text(" ", strip=True) for x in operator_nodes
                                 if not re.search(r"тур с", x.get_text(), re.I)), None)
                offers.append({"provider": "ozon_travel", "hotel_name": hotel_name,
                               "room_name": room_title.get_text(" ", strip=True), "meal_plan": meal,
                               "operator": operator, "departure_date": start.isoformat(),
                               "stay_end_date": finish.isoformat(), "return_date": None, "nights": n,
                               "adults": int(context["Dlts"]),
                               "child_ages": [int(x) for x in context.get("Children", "").split(",") if x],
                               "rooms": 1, "total_price": price, "currency": "RUB",
                               "price_per_night": round(price/n, 2), "flight_included": True,
                               "flight_selection_pending": True, "baggage": None, "transfer": None,
                               "availability": "quoted_not_booked", "source_url": data["url"],
                               "evidence": text})
    return sorted(offers, key=lambda x: x["total_price"])[:limit]


class OzonToursAdapter:
    def __init__(self, browser: OzonToursBrowser, access):
        self.browser, self.access = browser, access

    @contextmanager
    def _lock(self):
        self.access.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(str(self.access.path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(fd, "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield

    async def _request(self, client, path, payload=None):
        r = (await client.get(path, params={"userId": USER_ID}) if payload is None else
             await client.post(path, json={"userId": USER_ID, **payload}))
        r.raise_for_status()
        return r.json()

    async def _capture(self, client, tab_id):
        return (await self._request(client, f"/tabs/{tab_id}/evaluate", {"expression": _CAPTURE}))["result"]

    async def _guard(self, client, tab_id):
        from html import escape
        from marketplaces_mcp.core.ozon_tours_access import classify_page
        data = (await self._request(client, f"/tabs/{tab_id}/evaluate", {"expression": _PAGE_EVIDENCE}))["result"]
        status = "OZON_TOURS_CAPTCHA_REQUIRED" if data.get("captcha_frame") else classify_page(
            "<title>" + escape(data.get("title", "")) + "</title><p>" + escape(data.get("text", "")) + "</p>")
        if status in {"OZON_TOURS_CAPTCHA_REQUIRED", "OZON_TOURS_BLOCKED"}:
            self.access.write({"status": status, "browser_tab_id": tab_id,
                               "checked_at": time.time(), "retry_after": time.time()+1800})
            raise ValueError(status)

    def _access_response(self, source_url, state):
        warnings = [state["status"]]
        if state["status"] in {"OZON_TOURS_BLOCKED", "OZON_TOURS_CAPTCHA_REQUIRED"}:
            warnings.append("CAPTCHA_OR_BLOCKED")
        return {"provider": "ozon_travel", "source_url": source_url, "offers": [],
                "access": state, "warnings": warnings}

    async def search(self, *, limit=10, **kwargs):
        url = build_search_url(**kwargs)
        with self._lock():
            prior = self.access.read()
            if self.access.navigation_blocked(prior):
                return self._access_response(url, prior)
            state = await self.browser.inspect(allow_navigation=True)
            if state["status"] not in {"OZON_TOURS_PAGE_AVAILABLE", "OZON_TOURS_CONTENT_UNVERIFIED"}:
                if state["status"] in {"OZON_TOURS_BLOCKED", "OZON_TOURS_CAPTCHA_REQUIRED"}:
                    self.access.write({**state, "checked_at": time.time(), "retry_after": time.time()+1800})
                    state = self.access.read()
                return self._access_response(url, state)
            tab_id = state["browser_tab_id"]
            async with httpx.AsyncClient(base_url=self.browser.base_url, timeout=35) as c:
                current = await self._capture(c, tab_id)
                try:
                    same = search_context(current["url"]) == search_context(url)
                except ValueError:
                    same = False
                if not same:
                    try:
                        await self._request(c, f"/tabs/{tab_id}/navigate", {"url": url})
                    except (httpx.TimeoutException, httpx.HTTPStatusError):
                        pass
                # Keep the same browser while the tour operators finish their search.
                for attempt in range(18):
                    await self._guard(c, tab_id)
                    data = await self._capture(c, tab_id)
                    if data.get("html") and not data.get("loading"):
                        break
                    await asyncio.sleep(3)
                offers = parse_leads(data, url, max(1, min(limit, 30)))
                self.access.write({"status": "OZON_TOURS_PAGE_AVAILABLE", "checked_at": time.time(),
                                   "retry_after": 0, "browser_tab_id": tab_id})
                return {"provider": "ozon_travel", "source_url": url, "browser_tab_id": tab_id,
                        "checked_at": time.time(), "offers": offers,
                        "warnings": ["ROOM_MEAL_RATE_REQUIRED", "SEARCH_RESULTS_MAY_BE_PARTIAL"],
                        "note": "Hotel leads only. Search-card prices do not prove the selected meal plan. Call ozon_travel_tour_details."}

    async def details(self, *, search_url, hotel_name, all_inclusive_only=True, limit=20):
        expected = search_context(search_url)
        with self._lock():
            prior = self.access.read()
            if self.access.navigation_blocked(prior):
                return self._access_response(search_url, prior)
            async with httpx.AsyncClient(base_url=self.browser.base_url, timeout=35) as c:
                tabs = (await self._request(c, "/tabs"))["tabs"]
                matching = []
                for t in tabs:
                    try:
                        if search_context(t["url"]) == expected:
                            matching.append(t)
                    except ValueError:
                        pass
                if len(matching) != 1:
                    raise ValueError("Search tab is missing or ambiguous; call ozon_travel_tours_search")
                tab_id = matching[0]["tabId"]
                await self._guard(c, tab_id)
                data = await self._capture(c, tab_id)
                leads = parse_leads(data, search_url, 100)
                if sum(x["hotel_name"] == hotel_name for x in leads) != 1:
                    raise ValueError("Hotel is not a unique current search result")
                old_ids = {x["tabId"] for x in tabs}
                selector = ('[data-widget=toursSearchResult] [gallerytrackinginfo]:has('
                            'span.tsBodyControl500Medium:text-is(' + json.dumps(hotel_name) + ')) button')
                await self._request(c, f"/tabs/{tab_id}/click", {"selector": selector})
                detail_id = None
                for attempt in range(15):
                    tabs = (await self._request(c, "/tabs"))["tabs"]
                    new = [t for t in tabs if t["tabId"] not in old_ids and
                           urlsplit(t["url"]).path == "/travel/tours/hotel"]
                    if len(new) == 1:
                        detail_id = new[0]["tabId"]
                        await self._guard(c, detail_id)
                        data = await self._capture(c, detail_id)
                        if data.get("detail") and "тур с" in BeautifulSoup(data["detail"], "html.parser").get_text(" "):
                            break
                    elif len(new) > 1:
                        raise ValueError("Multiple detail tabs opened")
                    await asyncio.sleep(2)
                if not detail_id:
                    raise ValueError("Ozon did not open a room-selection page")
                offers = parse_rates(data, search_url, hotel_name, all_inclusive_only, max(1, min(limit, 30)))
                return {"provider": "ozon_travel", "source_url": search_url,
                        "checked_at": time.time(), "offers": offers,
                        "browser_tab_id": detail_id, "warnings": ["FINAL_FLIGHT_SELECTION_PENDING", "SINGLE_ROOM_QUOTE"],
                        "note": "Read-only room/operator quotes; flight choice, baggage, transfer and final booking total need confirmation."}
