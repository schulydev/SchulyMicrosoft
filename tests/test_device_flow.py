"""Device-code start/poll, driven against a fake Microsoft token endpoint."""

import httpx
import pytest
from fastapi.testclient import TestClient

from src import outnote_client
from src.app import app


class FakeNote:
    def me(self):
        return {"id": "user-1", "mail": "alex@school.ch", "displayName": "Alex Muster"}


class FakeBroker:
    def __init__(self, refresh_token):
        self.refresh_token = refresh_token


@pytest.fixture
def mock_ms(monkeypatch):
    state = {"stage": "pending"}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/devicecode"):
            return httpx.Response(200, json={"device_code": "DEV-CODE", "user_code": "ABCD-EFGH", "verification_uri": "https://microsoft.com/devicelogin", "interval": 1, "expires_in": 900, "message": "enter ABCD-EFGH"})
        if state["stage"] == "pending":
            state["stage"] = "done"
            return httpx.Response(400, json={"error": "authorization_pending"})
        return httpx.Response(200, json={"access_token": "at", "refresh_token": "new-frt", "expires_in": 3600})

    transport = httpx.MockTransport(handler)
    original = outnote_client._post

    async def patched(url, data, client=None):
        async with httpx.AsyncClient(transport=transport) as c:
            return await original(url, data, c)

    monkeypatch.setattr(outnote_client, "_post", patched)
    monkeypatch.setattr(outnote_client, "build_client", lambda frt: (FakeNote(), FakeBroker(frt)))
    return state


def test_device_start_returns_the_user_code(mock_ms):
    client = TestClient(app)
    r = client.post("/api/auth/device/start")
    assert r.status_code == 200
    body = r.json()
    assert body["user_code"] == "ABCD-EFGH"
    assert body["device_code"] == "DEV-CODE"
    assert "devicelogin" in body["verification_uri"]


def test_device_poll_pending_then_complete(mock_ms):
    client = TestClient(app)
    pending = client.post("/api/auth/device/poll", json={"device_code": "DEV-CODE"}).json()
    assert pending["status"] == "pending"

    complete = client.post("/api/auth/device/poll", json={"device_code": "DEV-CODE"}).json()
    assert complete["status"] == "complete"
    assert complete["refresh_token"] == "new-frt"
    assert complete["account"]["email"] == "alex@school.ch"
    assert complete["account"]["name"] == "Alex Muster"
