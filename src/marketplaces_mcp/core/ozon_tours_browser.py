"""Keep the Ozon page across navigation timeouts and manual verification."""
from __future__ import annotations

import asyncio
import httpx
from urllib.parse import urlsplit

URL = "https://www.ozon.ru/travel/tours/"
USER_ID = "marketplaces-ozon-tours-readonly"

# Return only visible state and a boolean, never the signed CAPTCHA URL.
_PAGE_EVIDENCE = """(() => ({
 title: document.title,
 text: document.body ? document.body.innerText.slice(0, 60000) : '',
 captcha_frame: Array.from(document.querySelectorAll('iframe')).some(f => {
   const r = f.getBoundingClientRect();
   if (!r.width || !r.height || getComputedStyle(f).visibility === 'hidden') return false;
   try { const u = new URL(f.src); return u.protocol === 'https:' &&
     u.hostname === 'www.ozon.ru' && u.pathname === '/captcha.html'; }
   catch { return false; }
 })
}))()"""


def _is_tours_url(url: str) -> bool:
    p = urlsplit(url)
    return p.scheme == "https" and p.hostname == "www.ozon.ru" and (
        p.path.rstrip("/") in {"/travel/tours", "/travel/tours/search"}
    )


class OzonToursBrowser:
    def __init__(self, base_url: str, *, transport=None):
        self.base_url = base_url
        self.transport = transport

    async def inspect(self, *, allow_navigation: bool = False):
        if not self.base_url:
            return {"status": "OZON_TOURS_BROWSER_NOT_CONFIGURED"}
        async with httpx.AsyncClient(base_url=self.base_url, transport=self.transport,
                                     timeout=35) as client:
            listed = await client.get("/tabs", params={"userId": USER_ID})
            listed.raise_for_status()
            tabs = [t for t in listed.json().get("tabs", [])
                    if t.get("listItemId") == "readonly" and _is_tours_url(t.get("url", ""))]
            if len(tabs) > 1:
                return {"status": "OZON_TOURS_MULTIPLE_TABS", "tab_count": len(tabs)}
            if tabs:
                tab_id = tabs[0].get("tabId") or tabs[0].get("targetId")
            elif not allow_navigation:
                return {"status": "OZON_TOURS_NO_OPEN_TAB"}
            else:
                # Allocate separately: a slow goto must not lose the tab ID.
                created = await client.post("/tabs", json={"userId": USER_ID, "sessionKey": "readonly"})
                created.raise_for_status()
                tab_id = created.json().get("tabId")
                if not tab_id:
                    raise ValueError("Camofox did not return a tab ID")
                try:
                    nav = await client.post(f"/tabs/{tab_id}/navigate", json={"userId": USER_ID, "url": URL})
                    nav.raise_for_status()
                except (httpx.TimeoutException, httpx.HTTPStatusError):
                    # Read the same page, including CAPTCHA, before calling this a network failure.
                    pass
            if not tab_id or not isinstance(tab_id, str):
                raise ValueError("Invalid tab ID")
            for attempt in range(5):
                response = await client.post(f"/tabs/{tab_id}/evaluate", json={
                    "userId": USER_ID, "expression": _PAGE_EVIDENCE})
                response.raise_for_status()
                evidence = response.json().get("result")
                if not isinstance(evidence, dict):
                    raise ValueError("Missing browser evidence")
                from marketplaces_mcp.core.ozon_tours_access import classify_page
                from html import escape
                status = ("OZON_TOURS_CAPTCHA_REQUIRED" if evidence.get("captcha_frame") is True
                          else classify_page("<title>" + escape(str(evidence.get("title", ""))) +
                                             "</title><p>" + escape(str(evidence.get("text", ""))) + "</p>"))
                if status != "OZON_TOURS_CONTENT_UNVERIFIED" or attempt == 4:
                    break
                await asyncio.sleep(2)
            return {"status": status, "browser_tab_id": tab_id, "browser_user_id": USER_ID,
                    "requires_user_action": status == "OZON_TOURS_CAPTCHA_REQUIRED",
                    "tab_preserved": True,
                    "next_step": ("Complete Ozon verification in this same browser tab; then inspect_tab=true. "
                                  "Do not create another profile or copy cookies.")
                    if status == "OZON_TOURS_CAPTCHA_REQUIRED" else "Inspect the retained tab; page access alone is not a package quote."}

    async def __call__(self, url: str):
        if url != URL:
            raise ValueError("Only the Ozon tours landing page is supported")
        return await self.inspect(allow_navigation=True)
