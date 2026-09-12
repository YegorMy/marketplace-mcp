from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import pytest

from marketplaces_mcp.adapters.avito import AvitoAdapter, _block_reason, _locked_state
from marketplaces_mcp.core.config import Settings


DETAIL_URL = "https://www.avito.ru/moskva/igry_pristavki/mario_kart_world_1234567890"
HEALTHY_DETAIL = """
- heading "Mario Kart World для Nintendo Switch 2" [level=1]
- text: 5 500 ₽
- heading "Описание" [level=2]
- paragraph: Если VPN показывает Forbidden или CAPTCHA, отключите его.
"""


def _settings(state_path: Path, *, interval: float = 0) -> Settings:
    return Settings(
        avito_state_path=state_path,
        avito_min_interval_seconds=interval,
        avito_block_cooldown_seconds=600,
        camofox_url="http://127.0.0.1:9377",
    )


def _write_state(path: Path, state: dict[str, object]) -> None:
    path.write_text(json.dumps(state), encoding="utf-8")


def _read_state(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_shared_gate_allows_only_one_in_flight_browser_read(tmp_path, monkeypatch):
    async def run():
        settings = _settings(tmp_path / "avito.json")
        first = AvitoAdapter(settings)
        second = AvitoAdapter(settings)
        entered = asyncio.Event()
        release = asyncio.Event()
        active = 0
        maximum_active = 0

        async def held_snapshot(_url: str):
            nonlocal active, maximum_active
            active += 1
            maximum_active = max(maximum_active, active)
            entered.set()
            try:
                await release.wait()
                return HEALTHY_DETAIL
            finally:
                active -= 1

        async def forbidden_second_snapshot(_url: str):
            raise AssertionError("a second profile must not open a browser while the lease is held")

        monkeypatch.setattr(first, "_fetch_with_camofox", held_snapshot)
        monkeypatch.setattr(second, "_fetch_with_camofox", forbidden_second_snapshot)
        first_task = asyncio.create_task(first._fetch_live_snapshot(DETAIL_URL))
        await entered.wait()
        second_result = await second._fetch_live_snapshot(DETAIL_URL)
        release.set()
        first_result = await first_task
        return first_result, second_result, maximum_active

    first_result, second_result, maximum_active = asyncio.run(run())
    assert first_result == (HEALTHY_DETAIL, ["CAMOFOX_READONLY"])
    assert second_result == (None, ["AVITO_REQUEST_IN_PROGRESS"])
    assert maximum_active == 1


def test_waiting_lease_rechecks_cooldown_before_navigation(tmp_path, monkeypatch):
    async def run():
        state_path = tmp_path / "avito.json"
        _write_state(state_path, {"last_request_at": time.time()})
        adapter = AvitoAdapter(_settings(state_path, interval=0.05))
        browser_calls = 0

        async def impose_challenge_during_wait(_seconds: float):
            adapter._finish_live_lease(
                "another-profile", "AVITO_CHALLENGE_REQUIRED", "AVITO_CHALLENGE_REQUIRED"
            )

        async def forbidden_snapshot(_url: str):
            nonlocal browser_calls
            browser_calls += 1
            raise AssertionError("cooldown discovered after the wait must prevent navigation")

        monkeypatch.setattr("marketplaces_mcp.adapters.avito.anyio.sleep", impose_challenge_during_wait)
        monkeypatch.setattr(adapter, "_fetch_with_camofox", forbidden_snapshot)
        result = await adapter._fetch_live_snapshot(DETAIL_URL)
        return result, browser_calls, _read_state(state_path)

    result, browser_calls, state = asyncio.run(run())
    assert result == (None, ["AVITO_ACCESS_COOLDOWN"])
    assert browser_calls == 0
    assert state["blocked_reason"] == "AVITO_CHALLENGE_REQUIRED"
    assert "in_flight_token" not in state
    assert "in_flight_until" not in state


def test_cancellation_releases_only_the_owned_lease(tmp_path, monkeypatch):
    async def run():
        state_path = tmp_path / "avito.json"
        adapter = AvitoAdapter(_settings(state_path))
        entered = asyncio.Event()

        async def held_snapshot(_url: str):
            entered.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(adapter, "_fetch_with_camofox", held_snapshot)
        task = asyncio.create_task(adapter._fetch_live_snapshot(DETAIL_URL))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return _read_state(state_path)

    state = asyncio.run(run())
    assert "in_flight_token" not in state
    assert "in_flight_until" not in state
    assert state["last_result"] == "AVITO_TRANSPORT_INTERRUPTED"


def test_expired_crash_lease_can_be_replaced(tmp_path):
    state_path = tmp_path / "avito.json"
    _write_state(
        state_path,
        {"in_flight_token": "dead-process", "in_flight_until": time.time() - 1},
    )
    adapter = AvitoAdapter(_settings(state_path))

    allowed, wait, warning = adapter._acquire_live_lease("replacement")

    assert (allowed, wait, warning) == (True, 0, "")
    state = _read_state(state_path)
    assert state["in_flight_token"] == "replacement"
    assert float(state["in_flight_until"]) > time.time()


def test_corrupt_state_fails_closed_without_fetch_or_rewrite(tmp_path, monkeypatch):
    async def run():
        state_path = tmp_path / "avito.json"
        corrupt = '{"blocked_until":'
        state_path.write_text(corrupt, encoding="utf-8")
        adapter = AvitoAdapter(_settings(state_path))
        browser_calls = 0

        async def forbidden_snapshot(_url: str):
            nonlocal browser_calls
            browser_calls += 1
            return HEALTHY_DETAIL

        monkeypatch.setattr(adapter, "_fetch_with_camofox", forbidden_snapshot)
        fetch_result = await adapter._fetch_live_snapshot(DETAIL_URL)
        status = await adapter.access_status()
        return fetch_result, status, browser_calls, state_path.read_text(encoding="utf-8")

    fetch_result, status, browser_calls, contents = asyncio.run(run())
    assert fetch_result == (None, ["AVITO_ACCESS_STATE_INVALID"])
    assert status == {
        "state": "error",
        "reason": "AVITO_ACCESS_STATE_INVALID",
        "live_request_allowed": False,
        "price_verified": False,
    }
    assert browser_calls == 0
    assert contents == '{"blocked_until":'


def test_failed_atomic_publish_keeps_last_valid_state(tmp_path, monkeypatch):
    state_path = tmp_path / "avito.json"
    original = {"blocked_until": time.time() + 600, "blocked_reason": "AVITO_IP_BLOCKED"}
    _write_state(state_path, original)
    original_bytes = state_path.read_bytes()

    def failed_replace(_source, _destination):
        raise OSError("simulated publish failure")

    monkeypatch.setattr("marketplaces_mcp.adapters.avito.os.replace", failed_replace)
    with pytest.raises(OSError, match="simulated publish failure"):
        with _locked_state(state_path) as state:
            state["last_result"] = "PAGE_READ"

    assert state_path.read_bytes() == original_bytes
    assert list(tmp_path.glob("avito.json.*")) == [tmp_path / "avito.json.lock"]


def test_legacy_cooldown_is_preserved_and_reported_as_ip_cooldown(tmp_path, monkeypatch):
    async def run():
        state_path = tmp_path / "avito.json"
        blocked_until = time.time() + 600
        _write_state(state_path, {"blocked_at": time.time(), "blocked_until": blocked_until})
        adapter = AvitoAdapter(_settings(state_path))

        async def forbidden_snapshot(_url: str):
            raise AssertionError("legacy cooldown must prevent a browser read")

        monkeypatch.setattr(adapter, "_fetch_with_camofox", forbidden_snapshot)
        fetch_result = await adapter._fetch_live_snapshot(DETAIL_URL)
        status = await adapter.access_status()
        return blocked_until, fetch_result, status, _read_state(state_path)

    blocked_until, fetch_result, status, state = asyncio.run(run())
    assert fetch_result == (None, ["AVITO_IP_COOLDOWN"])
    assert status["state"] == "cooldown"
    assert status["reason"] == "legacy_unclassified_block"
    assert status["live_request_allowed"] is False
    assert state["blocked_until"] == blocked_until
    assert "blocked_reason" not in state


@pytest.mark.parametrize(
    ("state", "interval", "expected_state", "expected_reason"),
    [
        (
            {"blocked_until": time.time() + 600, "blocked_reason": "AVITO_CHALLENGE_REQUIRED"},
            60,
            "cooldown",
            "AVITO_CHALLENGE_REQUIRED",
        ),
        (
            {"in_flight_until": time.time() + 600, "in_flight_token": "owner"},
            60,
            "busy",
            "AVITO_REQUEST_IN_PROGRESS",
        ),
        (
            {"last_request_at": time.time()},
            60,
            "rate_wait",
            "AVITO_RATE_LIMIT_WAIT",
        ),
        ({}, 60, "ready_for_probe", None),
    ],
)
def test_access_status_reports_gate_state_without_fetch(
    tmp_path, monkeypatch, state, interval, expected_state, expected_reason
):
    async def run():
        state_path = tmp_path / "avito.json"
        _write_state(state_path, state)
        adapter = AvitoAdapter(_settings(state_path, interval=interval))

        async def forbidden_snapshot(_url: str):
            raise AssertionError("access_status is read-only and must not fetch")

        monkeypatch.setattr(adapter, "_fetch_with_camofox", forbidden_snapshot)
        return await adapter.access_status()

    status = asyncio.run(run())
    assert status["state"] == expected_state
    assert status["reason"] == expected_reason
    assert status["live_request_allowed"] is (expected_state == "ready_for_probe")
    assert status["price_verified"] is False


@pytest.mark.parametrize(
    "snapshot",
    [
        HEALTHY_DETAIL,
        """
        <html><head><title>Mario Kart World</title></head><body>
          <h1>Mario Kart World для Nintendo Switch 2</h1>
          <div data-marker="item-view/item-description">
            VPN, CAPTCHA, Forbidden и Access denied перечислены в описании продавца.
          </div>
        </body></html>
        """,
    ],
)
def test_security_words_inside_healthy_product_are_not_blocks(snapshot):
    assert _block_reason(snapshot) is None
    assert AvitoAdapter()._is_blocked(snapshot) is False


@pytest.mark.parametrize(
    ("snapshot", "reason", "next_warning"),
    [
        (
            '- heading "Доступ ограничен: проблема с IP" [level=2]',
            "AVITO_IP_BLOCKED",
            "AVITO_IP_COOLDOWN",
        ),
        (
            '- heading "Подтвердите, что вы человек" [level=2]',
            "AVITO_CHALLENGE_REQUIRED",
            "AVITO_ACCESS_COOLDOWN",
        ),
    ],
)
def test_ip_and_challenge_have_distinct_reason_and_cooldown(
    tmp_path, monkeypatch, snapshot, reason, next_warning
):
    async def run():
        state_path = tmp_path / "avito.json"
        adapter = AvitoAdapter(_settings(state_path))

        async def blocked_snapshot(_url: str):
            return snapshot

        monkeypatch.setattr(adapter, "_fetch_with_camofox", blocked_snapshot)
        first = await adapter._fetch_live_snapshot(DETAIL_URL)
        second = await AvitoAdapter(adapter.settings)._fetch_live_snapshot(DETAIL_URL)
        return first, second, _read_state(state_path)

    first, second, state = asyncio.run(run())
    assert reason in first[1]
    assert "CAPTCHA_OR_BLOCKED" in first[1]
    assert second == (None, [next_warning])
    assert state["blocked_reason"] == reason
    assert state["block_classifier_version"] == 2
    assert os.stat(tmp_path / "avito.json").st_mode & 0o777 == 0o600
