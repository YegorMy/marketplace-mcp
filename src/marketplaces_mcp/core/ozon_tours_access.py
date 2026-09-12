"""Bounded, shared Ozon tours diagnostics; an accessible page is not a quote."""
from __future__ import annotations

import asyncio
import fcntl
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time

from bs4 import BeautifulSoup

URL = "https://www.ozon.ru/travel/tours/"


def classify_page(text: str | None) -> str:
    if not text or not text.strip():
        return "OZON_TOURS_CONTENT_UNVERIFIED"
    soup = BeautifulSoup(text, "html.parser")
    headings = " ".join(x.get_text(" ", strip=True) for x in soup.select("h1,h2,title"))
    headings += " ".join(re.findall(r'heading "([^"\n]+)"', text))
    if re.search(r"antibot captcha|сопоставьте пазл|slide the slider|подтвердите,? что вы не бот", headings, re.I):
        return "OZON_TOURS_CAPTCHA_REQUIRED"
    # Match block-page headings, not incidental words in descriptions/scripts.
    if re.search(r"похоже, нет\s+соединения|доступ ограничен|проблема с ip|access denied|подтвердите.*человек", headings, re.I):
        return "OZON_TOURS_BLOCKED"
    for element in soup.select("script,style,noscript"):
        element.decompose()
    visible = soup.get_text(" ", strip=True).lower()
    if all(part in visible for part in ("город вылета", "ночей", "найти туры")):
        return "OZON_TOURS_PAGE_AVAILABLE"
    return "OZON_TOURS_CONTENT_UNVERIFIED"


class OzonToursAccess:
    def __init__(self, probe_page, state_path: Path | None = None):
        self.probe_page = probe_page
        self.path = state_path or Path.home() / ".cache/marketplace-mcp/ozon-tours-access.json"

    def read(self):
        try:
            data = json.loads(self.path.read_text())
            if (not isinstance(data, dict) or not isinstance(data.get("status"), str)
                    or type(data.get("retry_after")) not in (float, int)
                    or not math.isfinite(data["retry_after"]) or data["retry_after"] < 0):
                raise ValueError("Invalid state")
        except FileNotFoundError:
            data = {"status": "OZON_TOURS_NOT_CHECKED", "retry_after": 0}
        except (ValueError, OSError):
            data = {"status": "OZON_TOURS_STATE_ERROR", "retry_after": 0}
        return {**data, "source_url": URL, "search_supported": True,
                "note": "Use ozon_travel_tours_search then ozon_travel_tour_details; a search-card price is not a verified meal-plan price.",
                "retry_allowed": data["retry_after"] <= time.time() and data["status"] != "OZON_TOURS_STATE_ERROR"}

    def write(self, data):
        fd, name = tempfile.mkstemp(prefix=".ozon-tours-", dir=self.path.parent)
        with os.fdopen(fd, "w") as out:
            json.dump(data, out)
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, self.path)

    def navigation_blocked(self, state=None) -> bool:
        state = self.read() if state is None else state
        return (state["status"] == "OZON_TOURS_STATE_ERROR"
                or (state["status"] in {"OZON_TOURS_BLOCKED", "OZON_TOURS_CAPTCHA_REQUIRED",
                                        "OZON_TOURS_PROBE_INTERRUPTED_OR_RUNNING"}
                    and not state["retry_allowed"]))

    async def status(self, probe: bool = False, inspect_tab: bool = False):
        prior = self.read()
        if not inspect_tab and (not probe or not prior["retry_allowed"]):
            return {**prior, "cached": True}
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(str(self.path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(fd, "w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return {**self.read(), "cached": True, "probe_in_progress": True}
            prior = self.read()
            if not inspect_tab and not prior["retry_allowed"]:
                return {**prior, "cached": True}
            now = time.time()
            # Persist before navigation: interruption must not open a retry storm.
            retry_after = prior["retry_after"] if inspect_tab else now + 1800
            if not inspect_tab:
                self.write({"status": "OZON_TOURS_PROBE_INTERRUPTED_OR_RUNNING", "checked_at": now, "retry_after": retry_after})
            try:
                result = await asyncio.wait_for(
                    self.probe_page.inspect(allow_navigation=False) if inspect_tab else self.probe_page(URL),
                    timeout=75,
                )
                evidence = result if isinstance(result, dict) else {"status": classify_page(result)}
            except Exception:
                evidence = {"status": "OZON_TOURS_NETWORK_ERROR"}
            self.write({**evidence, "checked_at": time.time(), "retry_after": retry_after,
                        "transport": "camofox"})
            return {**self.read(), "cached": False}
