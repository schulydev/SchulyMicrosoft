"""`/me` is asked once, without OutNote's Retry-After sleeps; on 429 the profile comes from the token's claims."""

import base64
import json
import time

import httpx
import pytest

from src import profile
from tests.conftest import REAL_FETCH


def _jwt(claims: dict) -> str:
    def part(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    return f"{part({'alg': 'none'})}.{part(claims)}.sig"


TOKEN = _jwt({"oid": "oid-1", "name": "Alex Muster", "upn": "alex@school.ch", "given_name": "Alex", "family_name": "Muster", "tid": "t"})


class Broker:
    def __init__(self, token=TOKEN):
        self.token = token
        self.minted = 0

    def __call__(self, client_id, scope=None):
        self.minted += 1
        return self.token


class Note:
    def me(self):
        raise AssertionError("OutNote's retrying read must not be used for /me")


class Http:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, headers))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def real(monkeypatch):
    monkeypatch.setattr(profile, "_fetch", REAL_FETCH)

    def use(*answers):
        http = Http(*answers)
        monkeypatch.setattr(profile, "http_client", lambda: http)
        return http
    return use


def test_a_throttled_me_falls_back_to_the_token_claims_at_once(real):
    http = real(httpx.Response(429, headers={"Retry-After": "21"}, json={"error": {"code": "TooManyRequests"}}))
    started = time.monotonic()
    me = profile.get(Note(), Broker())
    assert time.monotonic() - started < 1
    assert me == {"id": "oid-1", "displayName": "Alex Muster", "givenName": "Alex", "surname": "Muster", "userPrincipalName": "alex@school.ch", "mail": "alex@school.ch"}
    assert len(http.calls) == 1
    assert http.calls[0][1]["Authorization"] == f"Bearer {TOKEN}"


def test_a_me_answer_is_cached_for_an_hour(real):
    http = real(httpx.Response(200, json={"id": "oid-1", "displayName": "Alex", "mail": "a@school.ch"}))
    broker = Broker()
    assert profile.get(Note(), broker)["mail"] == "a@school.ch"
    assert profile.get(Note(), broker)["mail"] == "a@school.ch"
    assert len(http.calls) == 1


def test_a_claims_profile_is_kept_briefly_then_me_is_asked_again(real, monkeypatch):
    http = real(httpx.Response(429), httpx.Response(200, json={"id": "oid-1", "displayName": "Alex", "mail": "a@school.ch"}))
    broker = Broker()
    assert profile.get(Note(), broker)["mail"] == "alex@school.ch"
    assert profile.get(Note(), broker)["mail"] == "alex@school.ch"
    assert len(http.calls) == 1
    now = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: now + profile.CLAIMS_TTL + 1)
    assert profile.get(Note(), broker)["mail"] == "a@school.ch"
    assert len(http.calls) == 2


def test_a_network_failure_also_uses_the_claims(real):
    real(httpx.ConnectTimeout("slow"))
    assert profile.get(Note(), Broker())["id"] == "oid-1"


def test_without_claims_the_failure_is_reported(real):
    from outnote import GraphError
    real(httpx.Response(429))
    with pytest.raises(GraphError):
        profile.get(Note(), Broker(token="opaque-token"))


@pytest.mark.parametrize("token", ["", "a.b", "a.!!!.c", _jwt({"name": "no oid"}), _jwt(["list"])])
def test_tokens_without_a_user_give_no_claims_profile(token):
    assert profile.from_claims(token) is None
