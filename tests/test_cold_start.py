"""Cold start: one redeem for a burst, readiness while warming up, HTTP/1.1 clients, cached profile."""

import asyncio
import importlib
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import entrance
import pytest
from entrance import _foci, _http
from fastapi.testclient import TestClient

import src
from src import app as app_module
from src import config, outnote_client
from src.app import app
from src.outnote_client import _BrokerCache

HEADER = {config.REFRESH_TOKEN_HEADER: "frt-cold"}
REDEEM_SECONDS = 0.5


class BrokerNote:
    """Stands in for OutNote: every Graph call needs a token from the shared broker first."""

    def __init__(self, broker, profile_reads):
        self._broker = broker
        self._reads = profile_reads

    def me(self):
        self._broker("client")
        self._reads.append(1)
        return {"id": "u1", "displayName": "Alex"}


@pytest.fixture
def cold(monkeypatch):
    redeems = []

    def post(url, data):
        redeems.append(time.monotonic())
        if len(redeems) == 1:
            time.sleep(REDEEM_SECONDS)
        return {"access_token": "at", "refresh_token": data["refresh_token"], "expires_in": 3600}

    reads = []
    monkeypatch.setattr(_foci, "_post_token", post)
    monkeypatch.setattr(outnote_client, "_brokers", _BrokerCache())
    monkeypatch.setattr(outnote_client, "build_client", lambda token: (lambda b: (BrokerNote(b, reads), b))(outnote_client._brokers.get(token)))

    async def no_warm_up():
        return None

    monkeypatch.setattr(outnote_client, "warm_up", no_warm_up)
    return redeems, reads


def test_burst_on_a_cold_broker_redeems_once_and_waits_once(cold):
    redeems, reads = cold
    with TestClient(app) as client:
        started = time.monotonic()
        with ThreadPoolExecutor(5) as pool:
            codes = list(pool.map(lambda _: client.get("/api/me", headers=HEADER).status_code, range(5)))
        elapsed = time.monotonic() - started
    assert codes == [200] * 5
    assert len(redeems) == 1
    assert len(reads) == 1
    assert elapsed < REDEEM_SECONDS * 3


def test_me_is_fetched_once_for_repeated_calls(cold):
    _, reads = cold
    with TestClient(app) as client:
        bodies = [client.get("/api/me", headers=HEADER).json() for _ in range(3)]
        client.get("/api/me", headers={config.REFRESH_TOKEN_HEADER: "other"})
    assert bodies == [{"id": "u1", "displayName": "Alex"}] * 3
    assert len(reads) == 2


def test_ready_is_503_until_warm_up_finishes(monkeypatch):
    release = threading.Event()

    async def slow_warm_up():
        await asyncio.to_thread(release.wait, 10)

    monkeypatch.setattr(outnote_client, "warm_up", slow_warm_up)
    with TestClient(app) as client:
        assert client.get("/health/live").json() == {"status": "ok"}
        blocked = client.get("/health/ready")
        assert blocked.status_code == 503 and blocked.json() == {"status": "starting"}
        release.set()
        for _ in range(100):
            ready = client.get("/health/ready")
            if ready.status_code == 200:
                break
            time.sleep(0.02)
        assert ready.status_code == 200 and ready.json() == {"status": "ready"}
        assert client.get("/health/live").status_code == 200


def test_ready_after_grace_period_even_if_warm_up_hangs(monkeypatch):
    release = threading.Event()

    async def slow_warm_up():
        await asyncio.to_thread(release.wait, 10)

    monkeypatch.setattr(outnote_client, "warm_up", slow_warm_up)
    monkeypatch.setattr(app_module, "READY_GRACE", 0.0)
    with TestClient(app) as client:
        assert client.get("/health/ready").status_code == 200
        release.set()


def test_shared_clients_use_http1_by_default():
    assert sys.modules.get("h2", "missing") is None
    assert _http._http2() is False
    assert outnote_client._http2() is False


def test_ms_http2_opt_in_keeps_h2_importable(monkeypatch):
    monkeypatch.setenv("MS_HTTP2", "1")
    monkeypatch.setitem(sys.modules, "h2", None)
    monkeypatch.delitem(sys.modules, "h2")
    src._force_http1()
    assert "h2" not in sys.modules or sys.modules["h2"] is not None
    assert _http._http2() is True
    assert outnote_client._http2() is True
