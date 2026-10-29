"""Profile photos by e-mail: direct UPN lookup, mail filter fallback, per-account caching, throttling."""

import pytest
from fastapi.testclient import TestClient
from outnote import GraphError

from src import config, outnote_client
from src.app import app

H = {config.REFRESH_TOKEN_HEADER: "old-frt"}
JPEG = bytes([0xFF, 0xD8, 0xFF]) + b"photo"


class Broker:
    refresh_token = "old-frt"


class Note:
    def __init__(self, photos=None, users=None, throttle=False):
        self.photos = photos or {}
        self.users = users or {}
        self.throttle = throttle
        self.calls = []

    def get(self, path, params=None, raw=False):
        self.calls.append(path)
        if self.throttle:
            raise GraphError(429, "slow down")
        if path in self.photos:
            return self.photos[path]
        raise GraphError(404, "not found")

    def list(self, path, params=None, limit=None):
        self.calls.append(("filter", params["$filter"]))
        address = params["$filter"].split("'", 1)[1].rsplit("'", 1)[0].replace("''", "'")
        return [{"id": self.users[address]}] if address in self.users else []


@pytest.fixture
def use(monkeypatch):
    def install(note):
        broker = Broker()
        monkeypatch.setattr(outnote_client, "build_client", lambda frt: (note, broker))
        return note
    return install


def test_upn_lookup_uses_the_48px_variant(use):
    note = use(Note(photos={"users/ana@school.ch/photos/48x48/$value": JPEG}))
    r = TestClient(app).get("/api/people/photo", headers=H, params={"email": "Ana@School.ch"})
    assert r.status_code == 200 and r.content == JPEG
    assert r.headers["content-type"] == "image/jpeg" and r.headers["cache-control"] == "no-store"
    assert note.calls == ["users/ana@school.ch/photos/48x48/$value"]


def test_falls_back_to_the_mail_filter_and_escapes_it(use):
    note = use(Note(photos={"users/U1/photos/48x48/$value": JPEG}, users={"o'neil@school.ch": "U1"}))
    r = TestClient(app).get("/api/people/photo", headers=H, params={"email": "o'neil@school.ch"})
    assert r.status_code == 200
    assert ("filter", "mail eq 'o''neil@school.ch'") in note.calls


def test_external_people_are_404_and_the_miss_is_cached(use):
    note = use(Note())
    client = TestClient(app)
    assert client.get("/api/people/photo", headers=H, params={"email": "x@gmail.com"}).status_code == 404
    count = len(note.calls)
    assert client.get("/api/people/photo", headers=H, params={"email": "x@gmail.com"}).status_code == 404
    assert len(note.calls) == count


def test_found_photos_are_cached_per_account(use):
    note = use(Note(photos={"users/ana@school.ch/photos/48x48/$value": JPEG}))
    client = TestClient(app)
    client.get("/api/people/photo", headers=H, params={"email": "ana@school.ch"})
    client.get("/api/people/photo", headers=H, params={"email": "ana@school.ch"})
    assert len(note.calls) == 1


def test_bad_addresses_and_sizes_are_400(use):
    use(Note())
    client = TestClient(app)
    assert client.get("/api/people/photo", headers=H, params={"email": "not-an-address"}).status_code == 400
    assert client.get("/api/people/photo", headers=H, params={"email": "a@b.ch' or 1 eq 1"}).status_code == 400
    assert client.get("/api/people/photo", headers=H, params={"email": "a@b.ch", "size": 50}).status_code == 400


def test_throttling_is_429_with_retry_after(use):
    use(Note(throttle=True))
    r = TestClient(app).get("/api/people/photo", headers=H, params={"email": "ana@school.ch"})
    assert r.status_code == 429 and r.headers["retry-after"] == "30"
