#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

from hive_web_runtime.action_web.browser import ActionWebRuntime

LOG = logging.getLogger("camofox-bridge")


def _quote_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


class BrowserLoop:
    def __init__(self, headless: bool, snapshot_tokens: int):
        self.headless = headless
        self.snapshot_tokens = snapshot_tokens
        self.loop = asyncio.new_event_loop()
        self.runtime: ActionWebRuntime | None = None
        self.tabs: dict[str, str] = {}
        self._thread = threading.Thread(target=self._run_loop, name="camofox-bridge-loop", daemon=True)
        self._thread.start()
        self.submit(self._startup()).result(timeout=30)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    async def _startup(self) -> None:
        self.runtime = ActionWebRuntime()

    def submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    async def create_tab(self, user_id: str, url: str) -> dict[str, str]:
        if not self.runtime:
            raise RuntimeError("runtime is not initialized")
        tab_id = f"tab_{uuid.uuid4().hex[:12]}"
        session_id = f"{user_id}_{tab_id}"
        session = await self.runtime.session_create(name=session_id, headless=self.headless)
        await self.runtime.navigate(session.session_id, url=url)
        self.tabs[tab_id] = session.session_id
        return {"tabId": tab_id}

    async def snapshot(self, tab_id: str) -> dict[str, str]:
        if not self.runtime:
            raise RuntimeError("runtime is not initialized")
        session_id = self.tabs.get(tab_id)
        if not session_id:
            raise KeyError(f"unknown tab: {tab_id}")
        session = self.runtime._get(session_id)
        page = cast(Any, session.page)
        raw = await page.evaluate(
            """
(() => {
  function visible(el) {
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style && style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
  }
  function roleOf(el) {
    if (/^H[1-6]$/.test(el.tagName)) return 'heading';
    return el.getAttribute('role') || ({A:'link', BUTTON:'button', INPUT:'textbox', TEXTAREA:'textbox', SELECT:'combobox'}[el.tagName] || el.tagName.toLowerCase());
  }
  function nameOf(el) {
    return (el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.innerText || el.value || el.textContent || '').replace(/\s+/g, ' ').trim();
  }
  const selector = 'h1,h2,h3,h4,a[href],button,p,span,strong,li,[role]';
  const elements = Array.from(document.querySelectorAll(selector)).filter(visible).slice(0, 180).map(el => ({
    role: roleOf(el),
    level: /^H[1-6]$/.test(el.tagName) ? Number(el.tagName.slice(1)) : null,
    name: nameOf(el).slice(0, 500),
    href: el.href || ''
  })).filter(item => item.name);
  return {
    url: location.href,
    title: document.title,
    text: (document.body ? document.body.innerText : '').replace(/\s+/g, ' ').trim().slice(0, 12000),
    elements
  };
})()
"""
        )
        lines = [f"- page: {raw.get('title', '')}".rstrip(), f"  - /url: {raw.get('url', '')}"]
        seen: set[tuple[str, str, str]] = set()
        for item in raw.get("elements", []):
            role = str(item.get("role") or "element")
            name = _quote_text(str(item.get("name") or ""))
            if not name:
                continue
            key = (role, name, str(item.get("href") or ""))
            if key in seen:
                continue
            seen.add(key)
            if role == "heading":
                level = item.get("level") or 2
                lines.append(f'- heading "{name}" [level={level}]')
            elif role == "link":
                lines.append(f'- link "{name}":')
                href = str(item.get("href") or "")
                if href:
                    lines.append(f"  - /url: {href}")
            elif role == "button":
                lines.append(f'- button "{name}":')
            else:
                lines.append(f"- text: {name}")
        for line in str(raw.get("text") or "").splitlines():
            text = _quote_text(line.strip())
            if text:
                lines.append(f"- text: {text}")
        return {"snapshot": "\n".join(lines)}

    async def close_user_sessions(self, user_id: str) -> dict[str, Any]:
        if not self.runtime:
            raise RuntimeError("runtime is not initialized")
        closed = 0
        for tab_id, session_id in list(self.tabs.items()):
            if session_id.startswith(f"{user_id}_"):
                await self.runtime.close(session_id)
                self.tabs.pop(tab_id, None)
                closed += 1
        return {"ok": True, "closed": closed}

    def shutdown(self) -> None:
        async def _shutdown() -> None:
            if self.runtime:
                await self.runtime.shutdown()

        try:
            self.submit(_shutdown()).result(timeout=20)
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self._thread.join(timeout=5)


class Handler(BaseHTTPRequestHandler):
    bridge: BrowserLoop

    def do_GET(self) -> None:  # noqa: N802
        if self.path in {"/health", "/healthz"}:
            self._send_json({"ok": True})
            return
        parsed = urlparse(self.path)
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) == 3 and parts[0] == "tabs" and parts[2] == "snapshot":
            try:
                payload = self.bridge.submit(self.bridge.snapshot(parts[1])).result(timeout=120)
            except KeyError as exc:
                self._send_json({"error": str(exc)}, status=404)
                return
            except Exception as exc:  # pragma: no cover - exercised by live smoke
                LOG.exception("snapshot failed")
                self._send_json({"error": type(exc).__name__, "message": str(exc)}, status=500)
                return
            self._send_json(payload)
            return
        self._send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/tabs":
            self._send_json({"error": "not found"}, status=404)
            return
        payload = self._read_json()
        user_id = str(payload.get("userId") or "marketplaces-public")
        url = str(payload.get("url") or "")
        if not url:
            self._send_json({"error": "url is required"}, status=400)
            return
        try:
            result = self.bridge.submit(self.bridge.create_tab(user_id=user_id, url=url)).result(timeout=120)
        except Exception as exc:  # pragma: no cover - exercised by live smoke
            LOG.exception("tab create failed")
            self._send_json({"error": type(exc).__name__, "message": str(exc)}, status=500)
            return
        self._send_json(result)

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) == 2 and parts[0] == "sessions":
            user_id = parts[1]
        else:
            query = parse_qs(parsed.query)
            user_id = (query.get("userId") or [""])[0]
        if not user_id:
            self._send_json({"error": "userId is required"}, status=400)
            return
        try:
            result = self.bridge.submit(self.bridge.close_user_sessions(user_id)).result(timeout=60)
        except Exception as exc:  # pragma: no cover - exercised by live smoke
            LOG.exception("session close failed")
            self._send_json({"error": type(exc).__name__, "message": str(exc)}, status=500)
            return
        self._send_json(result)

    def log_message(self, format: str, *args: Any) -> None:
        LOG.info("%s - %s", self.address_string(), format % args)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Local Camofox-compatible read-only browser bridge for marketplaces-mcp")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--headful", action="store_true", help="Run browser headed instead of headless")
    parser.add_argument("--snapshot-tokens", type=int, default=12000)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    Handler.bridge = BrowserLoop(headless=not args.headful, snapshot_tokens=args.snapshot_tokens)
    server = ThreadingHTTPServer((args.host, args.port), Handler)

    def stop(_signum, _frame) -> None:
        LOG.info("shutting down")
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    LOG.info("listening on http://%s:%s", args.host, args.port)
    try:
        server.serve_forever()
    finally:
        Handler.bridge.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
