import anyio
import httpx
import json

from marketplaces_mcp.adapters.avito import AvitoAdapter
from marketplaces_mcp.adapters.ozon import OzonAdapter
from marketplaces_mcp.adapters import base
from marketplaces_mcp.core.config import Settings


def test_empty_initial_snapshot_is_retried_in_same_session(monkeypatch, tmp_path):
    calls = []
    reads = 0

    async def handler(request):
        nonlocal reads
        calls.append((request.method, request.url.path))
        if request.method == "POST":
            return httpx.Response(200, json={"tabId": "one-tab"})
        if request.method == "GET":
            reads += 1
            return httpx.Response(200, json={"snapshot": "" if reads == 1 else '- heading "Mario Kart World" [level=1]'})
        return httpx.Response(200, json={})

    client = httpx.AsyncClient
    monkeypatch.setattr(base.httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(handler), **kw))
    adapter = AvitoAdapter(Settings(camofox_url="http://browser.local", avito_state_path=tmp_path / "state.json"))
    adapter.camofox_wait_seconds = 0
    result = anyio.run(adapter._fetch_with_camofox, "https://www.avito.ru/all")
    assert "Mario Kart" in result
    assert reads == 2
    assert sum(method == "POST" for method, path in calls) == 1
    assert sum(method == "DELETE" for method, path in calls) == 1


def test_cancelled_snapshot_still_closes_anonymous_session(monkeypatch, tmp_path):
    async def run():
        entered = anyio.Event()
        closed = []

        async def handler(request):
            if request.method == "POST":
                return httpx.Response(200, json={"tabId": "one-tab"})
            if request.method == "GET":
                entered.set()
                await anyio.sleep_forever()
            if request.method == "DELETE":
                await anyio.sleep(0)
                closed.append(request.url.path)
            return httpx.Response(200, json={})

        client = httpx.AsyncClient
        monkeypatch.setattr(base.httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(handler), **kw))
        adapter = OzonAdapter(Settings(camofox_url="http://browser.local", avito_state_path=tmp_path / "state.json"))
        adapter.camofox_wait_seconds = 0
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(adapter._fetch_with_camofox, "https://www.avito.ru/all")
            await entered.wait()
            tasks.cancel_scope.cancel()
        assert len(closed) == 1
        assert closed[0].startswith("/sessions/marketplaces-public-")

    anyio.run(run)


def test_avito_search_and_detail_share_context_but_close_each_tab(monkeypatch, tmp_path):
    users = []
    closes = []

    async def handler(request):
        if request.method == "POST":
            users.append(json.loads(request.content)["userId"])
            return httpx.Response(200, json={"tabId": f"tab-{len(users)}"})
        if request.method == "GET":
            return httpx.Response(200, json={"snapshot": '- heading "Mario Kart World" [level=1]'})
        closes.append((request.url.path, request.url.params.get("userId")))
        return httpx.Response(200, json={})

    client = httpx.AsyncClient
    monkeypatch.setattr(base.httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(handler), **kw))

    async def run():
        for url in ("https://www.avito.ru/all", "https://www.avito.ru/moskva/igry/game_12345678"):
            adapter = AvitoAdapter(Settings(camofox_url="http://browser.local", avito_state_path=tmp_path / "state.json"))
            adapter.camofox_wait_seconds = 0
            await adapter._fetch_with_camofox(url)

    anyio.run(run)
    assert len(users) == 2 and users[0] == users[1]
    assert closes == [("/tabs/tab-1", users[0]), ("/tabs/tab-2", users[0])]
