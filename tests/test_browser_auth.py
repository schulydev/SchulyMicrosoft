"""Browser sign-in: a well-formed authorize URL, and a code exchange against a fake token endpoint."""

from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from src import browser_auth, outnote_client
from src.app import app


def test_start_builds_a_pkce_authorize_url():
    client = TestClient(app)
    body = client.post("/api/auth/browser/start").json()

    assert body["redirect_uri"] == browser_auth.NATIVE_REDIRECT
    assert len(body["code_verifier"]) >= 40
    query = parse_qs(urlparse(body["authorize_url"]).query)
    assert query["client_id"] == [browser_auth.OFFICEHOME_CLIENT_ID]
    assert query["response_type"] == ["code"]
    assert query["redirect_uri"] == [browser_auth.NATIVE_REDIRECT]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"]  # present and non-empty


class FakeNote:
    def me(self):
        return {"id": "u1", "mail": "alex@school.ch", "displayName": "Alex Muster"}


@pytest.fixture
def mock_token(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        seen.update(body)
        if body.get("code") == "good-code":
            return httpx.Response(200, json={"access_token": "at", "refresh_token": "frt-from-browser", "expires_in": 3600})
        return httpx.Response(400, json={"error": "invalid_grant", "error_description": "bad code"})

    original = outnote_client._post

    async def patched(url, data, client=None):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await original(url, data, c)

    monkeypatch.setattr(outnote_client, "_post", patched)
    monkeypatch.setattr(outnote_client, "build_client", lambda frt: (FakeNote(), type("B", (), {"refresh_token": frt})()))
    return seen


def test_complete_exchanges_the_code(mock_token):
    client = TestClient(app)
    r = client.post("/api/auth/browser/complete", json={"code": "good-code", "code_verifier": "verifier"}).json()

    assert r["status"] == "complete"
    assert r["refresh_token"] == "frt-from-browser"
    assert r["account"]["email"] == "alex@school.ch"
    assert mock_token["grant_type"] == "authorization_code"
    assert mock_token["code_verifier"] == "verifier"


def test_complete_reports_a_bad_code(mock_token):
    client = TestClient(app)
    r = client.post("/api/auth/browser/complete", json={"code": "nope", "code_verifier": "v"}).json()
    assert r["status"] == "error"
    assert "bad code" in r["message"]
