"""build_client shares one broker per refresh token, so repeat calls reuse access tokens and don't rotate."""

import pytest
from entrance import _foci

from src import outnote_client
from src.outnote_client import _BrokerCache


class Calls(list):
    clock = None


class Clock:
    now = 1000.0

    def time(self):
        return self.now


@pytest.fixture
def redeems(monkeypatch):
    calls = Calls()
    clock = Clock()
    monkeypatch.setattr(_foci, "time", clock)

    def post(url, data):
        calls.append(data)
        n = len(calls)
        return {"access_token": f"at{n}", "refresh_token": data["refresh_token"], "expires_in": 3600}

    monkeypatch.setattr(_foci, "_post_token", post)
    monkeypatch.setattr(outnote_client, "_brokers", _BrokerCache())
    calls.clock = clock
    return calls


def test_second_call_reuses_access_token_and_refresh_token(redeems):
    _, first = outnote_client.build_client("frt-a")
    assert first("client") == "at1"
    _, second = outnote_client.build_client("frt-a")
    assert second("client") == "at1"
    assert len(redeems) == 1
    assert second.refresh_token == "frt-a"


def test_rotated_token_hits_same_broker(monkeypatch, redeems):
    def post(url, data):
        redeems.append(data)
        return {"access_token": "at", "refresh_token": "frt-b", "expires_in": 3600}

    monkeypatch.setattr(_foci, "_post_token", post)
    _, first = outnote_client.build_client("frt-a")
    first("client")
    assert first.refresh_token == "frt-b"
    _, again = outnote_client.build_client("frt-b")
    again("client")
    assert again is first
    assert len(redeems) == 1


def test_expired_entry_redeems_again(redeems):
    _, broker = outnote_client.build_client("frt-a")
    broker("client")
    redeems.clock.now += 3600
    assert broker("client") == "at2"
    assert len(redeems) == 2


def test_clients_are_cached_separately(redeems):
    _, broker = outnote_client.build_client("frt-a")
    broker("office")
    broker("onenote")
    broker("office")
    assert len(redeems) == 2


def test_different_tokens_do_not_share(redeems):
    _, a = outnote_client.build_client("frt-a")
    _, b = outnote_client.build_client("frt-b")
    assert a is not b
    a("client")
    b("client")
    assert len(redeems) == 2


def test_cache_is_bounded_lru():
    cache = _BrokerCache(max_size=2)
    a = cache.get("a")
    cache.get("b")
    cache.get("a")
    cache.get("c")
    assert cache.get("a") is a
    assert len(cache._items) == 2
    assert all(len(k) == 64 for k in cache._items)
