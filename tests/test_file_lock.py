import asyncio
import errno
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from marketplaces_mcp.core import file_lock
from marketplaces_mcp.core.ozon_tours_access import OzonToursAccess
from marketplaces_mcp.adapters.ozon_tours import OzonToursAdapter


def test_native_lock_excludes_other_process_and_releases(tmp_path):
    path = tmp_path / "shared.lock"
    code = """
import sys
from marketplaces_mcp.core.file_lock import exclusive_file_lock
try:
    with exclusive_file_lock(sys.argv[1]):
        pass
except BlockingIOError:
    sys.exit(23)
"""
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    def contender():
        return subprocess.run([sys.executable, "-c", code, str(path)],
                              env=env, timeout=10, capture_output=True)
    with file_lock.exclusive_file_lock(path):
        result = contender()
        assert result.returncode == 23, result.stderr
    assert contender().returncode == 0
    with pytest.raises(ValueError), file_lock.exclusive_file_lock(path):
        raise ValueError("body failed")
    assert contender().returncode == 0


@pytest.mark.parametrize("error", [errno.EACCES, errno.EAGAIN, errno.EDEADLK, errno.EBADF])
def test_windows_nonblocking_errors_and_cleanup(tmp_path, monkeypatch, error):
    calls = []
    def locking(fd, mode, size):
        calls.append((fd, mode, size, os.lseek(fd, 0, os.SEEK_CUR)))
        raise OSError(error, "fixture")
    monkeypatch.setattr(file_lock, "fcntl", None)
    monkeypatch.setattr(file_lock, "msvcrt", SimpleNamespace(
        locking=locking, LK_NBLCK=2, LK_UNLCK=0))
    expected = BlockingIOError if error != errno.EBADF else OSError
    with pytest.raises(expected) as caught:
        with file_lock.exclusive_file_lock(tmp_path / "lock"):
            pytest.fail("must not enter")
    assert caught.value.errno == error
    assert len(calls) == 1 and calls[0][1:] == (2, 1, 0)
    with pytest.raises(OSError):
        os.fstat(calls[0][0])


def test_windows_unlocks_same_byte_on_exception(tmp_path, monkeypatch):
    calls = []
    def locking(fd, mode, size):
        calls.append((mode, size, os.lseek(fd, 0, os.SEEK_CUR)))
    monkeypatch.setattr(file_lock, "fcntl", None)
    monkeypatch.setattr(file_lock, "msvcrt", SimpleNamespace(
        locking=locking, LK_NBLCK=2, LK_UNLCK=0))
    with pytest.raises(ValueError):
        with file_lock.exclusive_file_lock(tmp_path / "lock"):
            raise ValueError("cancel")
    assert calls == [(2, 1, 0), (0, 1, 0)]


def test_missing_backend_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(file_lock, "fcntl", None)
    monkeypatch.setattr(file_lock, "msvcrt", None)
    with pytest.raises(RuntimeError):
        with file_lock.exclusive_file_lock(tmp_path / "lock"):
            pytest.fail("must not enter")


def test_access_and_adapter_share_lock_without_starting_probe(tmp_path):
    async def forbidden(*args, **kwargs):
        pytest.fail("busy lock must prevent navigation")
    access = OzonToursAccess(forbidden, tmp_path / "state.json")
    adapter = OzonToursAdapter(SimpleNamespace(inspect=forbidden), access)
    with adapter._lock():
        state = asyncio.run(access.status(probe=True))
        assert state["probe_in_progress"] and state["cached"]
        with pytest.raises(BlockingIOError):
            asyncio.run(adapter.search(departure_date="2026-12-19"))
    assert not access.path.exists()
    with adapter._lock():
        pass


def test_server_imports_without_fcntl():
    code = """
import builtins
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == "fcntl":
        raise ModuleNotFoundError("No module named 'fcntl'")
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from marketplaces_mcp.mcp_server import server
assert server.REQUIRED_TOOLS
"""
    result = subprocess.run([sys.executable, "-c", code], timeout=30,
                            capture_output=True)
    assert result.returncode == 0, result.stderr


def test_active_probe_excludes_adapter_and_cancellation_releases(tmp_path):
    async def run():
        entered = asyncio.Event()
        async def probe(url):
            entered.set()
            await asyncio.Event().wait()
        access = OzonToursAccess(probe, tmp_path / "state.json")
        adapter = OzonToursAdapter(None, access)
        task = asyncio.create_task(access.status(probe=True))
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            with pytest.raises(BlockingIOError):
                with adapter._lock():
                    pytest.fail("probe must exclude search")
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        with adapter._lock():
            pass
        assert not access.read()["retry_allowed"]
    asyncio.run(run())
