"""Read endpoints build a client from the caller's token and hand the rotated token back."""

import pytest
from fastapi.testclient import TestClient
from outnote import GraphError

from src import config, outnote_client
from src import app as app_module
from src.app import app


class FakeNote:
    def __init__(self, data):
        self._data = data

    def me(self):
        return {"id": "u", "displayName": "Alex"}

    def emails(self, folder, top, unread, search, select=None):
        return [{"folder": folder, "top": top, "unread": unread, "search": search}]

    def files(self, path, top):
        return [{"path": path}]

    def events(self, start, end, top):
        return [{"start": start, "end": end, "top": top}]


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


def test_calendar_passes_the_window(fake_client):
    client = TestClient(app)
    r = client.get("/api/calendar", headers={config.REFRESH_TOKEN_HEADER: "old-frt"}, params={"start": "2026-11-01T00:00:00Z", "end": "2026-12-01T00:00:00Z", "top": 300})
    assert r.status_code == 200
    assert r.json() == [{"start": "2026-11-01T00:00:00Z", "end": "2026-12-01T00:00:00Z", "top": 300}]


JPEG = bytes([0xFF, 0xD8]) + b"photo"
HEADERS = {config.REFRESH_TOKEN_HEADER: "old-frt"}


class ChatNote:
    sized_missing = False
    no_photo = False

    def __init__(self):
        self.calls = []

    def list(self, path, params=None, limit=None):
        self.calls.append(("list", path, params, limit))
        return [{"id": "m1", "chat": path.split("/")[2], "top": limit, "select": params.get("$select")}]

    def send_chat_message(self, chat_id, text):
        self.calls.append(("send", chat_id, text))
        return {"id": "new", "body": {"content": text}}

    def mark_chat_read(self, chat_id):
        self.calls.append(("read", chat_id))

    def get(self, path, params=None, raw=False):
        self.calls.append(("get", path, raw))
        if self.no_photo or (self.sized_missing and "photos/" in path):
            raise GraphError(404, "no photo")
        return JPEG


@pytest.fixture
def chat_note(monkeypatch):
    note = ChatNote()
    broker = FakeBroker("old-frt")

    def build(frt):
        broker.refresh_token = "rotated-frt"
        return note, broker

    monkeypatch.setattr(outnote_client, "build_client", build)
    return note


@pytest.fixture
def expired(monkeypatch):
    class Broken:
        refresh_token = "x"

    class Note:
        def __getattr__(self, name):
            def fail(*args, **kwargs):
                raise RuntimeError("AADSTS700082 invalid_grant: token expired")
            return fail

    monkeypatch.setattr(outnote_client, "build_client", lambda frt: (Note(), Broken()))


def test_chat_messages_returns_graph_messages_and_rotated_token(chat_note):
    r = TestClient(app).get("/api/chats/19:abc@thread.v2/messages", headers=HEADERS, params={"top": 10})
    assert r.status_code == 200
    assert r.json() == [{"id": "m1", "chat": "19:abc@thread.v2", "top": 10, "select": None}]
    assert r.headers[config.REFRESH_TOKEN_HEADER] == "rotated-frt"


def test_chat_messages_top_is_capped(chat_note):
    assert TestClient(app).get("/api/chats/c1/messages", headers=HEADERS, params={"top": 301}).status_code == 422


def test_chat_messages_expired_is_401(expired):
    assert TestClient(app).get("/api/chats/c1/messages", headers=HEADERS).status_code == 401


def test_chat_messages_bad_chat_id_is_400(chat_note):
    assert TestClient(app).get("/api/chats/bad$id/messages", headers=HEADERS).status_code == 400
    assert chat_note.calls == []


def test_send_chat_message_returns_created_message_and_rotated_token(chat_note):
    r = TestClient(app).post("/api/chats/c1/messages", headers=HEADERS, json={"text": "hello"})
    assert r.status_code == 200
    assert r.json()["id"] == "new"
    assert chat_note.calls == [("send", "c1", "hello")]
    assert r.headers[config.REFRESH_TOKEN_HEADER] == "rotated-frt"


def test_send_chat_message_rejects_empty_and_oversized_text(chat_note):
    client = TestClient(app)
    assert client.post("/api/chats/c1/messages", headers=HEADERS, json={"text": ""}).status_code == 422
    assert client.post("/api/chats/c1/messages", headers=HEADERS, json={"text": "x" * 4001}).status_code == 422


def test_send_chat_message_expired_is_401(expired):
    assert TestClient(app).post("/api/chats/c1/messages", headers=HEADERS, json={"text": "hi"}).status_code == 401


def test_send_chat_message_bad_chat_id_is_400(chat_note):
    assert TestClient(app).post("/api/chats/a%23b/messages", headers=HEADERS, json={"text": "hi"}).status_code == 400
    assert chat_note.calls == []


def test_mark_chat_read_is_204_with_rotated_token(chat_note):
    r = TestClient(app).post("/api/chats/c1/read", headers=HEADERS)
    assert r.status_code == 204
    assert r.content == b""
    assert chat_note.calls == [("read", "c1")]
    assert r.headers[config.REFRESH_TOKEN_HEADER] == "rotated-frt"


def test_mark_chat_read_expired_is_401(expired):
    assert TestClient(app).post("/api/chats/c1/read", headers=HEADERS).status_code == 401


def test_mark_chat_read_bad_chat_id_is_400(chat_note):
    assert TestClient(app).post("/api/chats/a%3Fb/read", headers=HEADERS).status_code == 400


def test_user_photo_returns_bytes_cache_header_and_rotated_token(chat_note):
    r = TestClient(app).get("/api/users/alex@school.ch/photo", headers=HEADERS, params={"size": 96})
    assert r.status_code == 200
    assert r.content == JPEG
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers[config.REFRESH_TOKEN_HEADER] == "rotated-frt"
    assert chat_note.calls == [("get", "users/alex@school.ch/photos/96x96/$value", "bytes")]


def test_user_photo_falls_back_to_unsized_photo(chat_note):
    chat_note.sized_missing = True
    r = TestClient(app).get("/api/users/u1/photo", headers=HEADERS)
    assert r.status_code == 200
    assert [c[1] for c in chat_note.calls] == ["users/u1/photos/64x64/$value", "users/u1/photo/$value"]


def test_user_photo_missing_is_404_and_still_rotates_token(chat_note):
    chat_note.no_photo = True
    r = TestClient(app).get("/api/users/u1/photo", headers=HEADERS)
    assert r.status_code == 404
    assert r.headers[config.REFRESH_TOKEN_HEADER] == "rotated-frt"


def test_user_photo_expired_is_401(expired):
    assert TestClient(app).get("/api/users/u1/photo", headers=HEADERS).status_code == 401


def test_user_photo_bad_user_id_or_size_is_400(chat_note):
    client = TestClient(app)
    assert client.get("/api/users/a%23b/photo", headers=HEADERS).status_code == 400
    assert client.get("/api/users/" + "a" * 201 + "/photo", headers=HEADERS).status_code == 400
    assert client.get("/api/users/u1/photo", headers=HEADERS, params={"size": 50}).status_code == 400
    assert chat_note.calls == []
