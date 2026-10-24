"""Read endpoints build a client from the caller's token and hand the rotated token back."""

import pytest
from fastapi.testclient import TestClient

from src import config, outnote_client
from src.app import app


class FakeNote:
    def __init__(self, data):
        self._data = data

    def me(self):
        return {"id": "u", "displayName": "Alex"}

    def emails(self, folder, top, unread, search):
        return [{"folder": folder, "top": top, "unread": unread, "search": search}]

    def files(self, path, top):
        return [{"path": path}]


class FakeBroker:
    def __init__(self, refresh_token, rotate_to=None):
        self._rotate = rotate_to
        self.refresh_token = refresh_token

    def read_done(self):
        if self._rotate:
            self.refresh_token = self._rotate


@pytest.fixture
def fake_client(monkeypatch):
    broker = FakeBroker("old-frt", rotate_to="rotated-frt")

    def build(frt):
        # Simulate the broker rotating the token during the read.
        broker.refresh_token = "rotated-frt"
        return FakeNote(frt), broker

    monkeypatch.setattr(outnote_client, "build_client", build)
    return broker


def test_mail_passes_query_and_returns_rotated_token(fake_client):
    client = TestClient(app)
    r = client.get("/api/mail", headers={config.REFRESH_TOKEN_HEADER: "old-frt"}, params={"folder": "sentitems", "unread": "true", "top": 10})
    assert r.status_code == 200
    assert r.json()[0] == {"folder": "sentitems", "top": 10, "unread": True, "search": None}
    assert r.headers[config.REFRESH_TOKEN_HEADER] == "rotated-frt"


def test_a_read_without_a_token_is_rejected():
    client = TestClient(app)
    assert client.get("/api/mail").status_code == 422


def test_an_expired_token_maps_to_401(monkeypatch):
    class Broken:
        refresh_token = "x"

    def build(frt):
        class Note:
            def files(self, path, top):
                raise RuntimeError("AADSTS700082 invalid_grant: token expired")
        return Note(), Broken()

    monkeypatch.setattr(outnote_client, "build_client", build)
    client = TestClient(app)
    r = client.get("/api/files", headers={config.REFRESH_TOKEN_HEADER: "dead"})
    assert r.status_code == 401
