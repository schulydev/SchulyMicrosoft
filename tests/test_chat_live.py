import asyncio
import json
import socket
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from src.api.app import app
from src.application.abstractions.i_chat_live import IChatLive
from src.domain.errors.service_error import ServiceError
from tests.services import config, outnote_client, services

live_chats = services.get(IChatLive)
H = {config.REFRESH_TOKEN_HEADER: "frt-1"}
CHAT = "19:g@thread.v2"


def event(kind, chat_id=CHAT, from_me=False, **rest):
    return SimpleNamespace(kind=kind, chat_id=chat_id, from_me=from_me, sender_name="Bo", message={"body": "secret"}, raw={"x": 1}, **rest)


class Feed:
    """Like OutNote's LiveConnection: iterating blocks until close(), and only close() stops it."""

    def __init__(self, events=(), end=False, fails=None):
        self.events, self.end, self.fails = list(events), end, fails
        self.closed = threading.Event()

    def close(self):
        self.closed.set()

    def __iter__(self):
        yield from self.events
        if self.fails:
            raise self.fails
        if not self.end:
            self.closed.wait(30)


class Broker:
    refresh_token = "frt-1"

    def __call__(self, *args):
        return "token"


class Note:
    def __init__(self, feed):
        self.feed = feed
        self.reconnect = None

    def listen(self, reconnect=True, presence=()):
        self.reconnect = reconnect
        return self.feed


@pytest.fixture
def client(monkeypatch):
    def build(feed):
        note = Note(feed)
        broker = Broker()
        monkeypatch.setattr(outnote_client, "build_client", lambda frt: (note, broker))
        return note, broker

    return build


async def _read(stream):
    return [json.loads(line) async for line in stream]


def test_a_stream_says_only_what_changed_where(client):
    feed = Feed([event("connected", None), event("message", from_me=True), event("message_updated"), event("message_deleted", "48:notes"), event("typing"), event("stop_typing"), event("presence"), event("other"), event("message", "../../me"), event("message", None), event("message", "bad id")], end=True)
    note, _ = client(feed)
    r = TestClient(app).get("/api/chats/live", headers=H)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson") and r.headers["cache-control"] == "no-store"
    assert [json.loads(line) for line in r.text.splitlines()] == [
        {"kind": "ping"},
        {"kind": "connected"},
        {"kind": "message", "chatId": CHAT, "fromMe": True},
        {"kind": "message_updated", "chatId": CHAT, "fromMe": False},
        {"kind": "message_deleted", "chatId": "48:notes", "fromMe": False},
    ]
    assert note.reconnect is False  # a broken feed must end the stream, so the caller knows
    assert feed.closed.is_set()


def test_a_broken_feed_ends_the_stream_without_its_error(client):
    feed = Feed([event("connected", None)], fails=OSError("token abc in this message"))
    client(feed)
    r = TestClient(app).get("/api/chats/live", headers=H)
    assert r.status_code == 200 and "abc" not in r.text and feed.closed.is_set()


def test_a_bad_token_is_refused_before_the_stream(client):
    client(Feed())
    assert TestClient(app).get("/api/chats/live", headers={config.REFRESH_TOKEN_HEADER: "has spaces in it"}).status_code == 401
    assert TestClient(app).get("/api/chats/live").status_code == 422


def test_quiet_streams_send_heartbeats(monkeypatch):
    monkeypatch.setattr(live_chats, "HEARTBEAT", 0.01)

    async def run():
        feed = Feed()
        stream = live_chats.open(Note(feed), Broker())
        lines = [await stream.__anext__() for _ in range(3)]
        await stream.aclose()
        return lines, feed

    lines, feed = asyncio.run(run())
    assert lines == [live_chats.PING] * 3 and feed.closed.is_set()


def test_streams_are_capped_per_account_and_a_closed_one_frees_its_place():
    async def run():
        broker = Broker()
        streams = [live_chats.open(Note(Feed()), broker) for _ in range(live_chats.MAX_PER_ACCOUNT)]
        for stream in streams:
            await stream.__anext__()
        with pytest.raises(ServiceError) as refused:
            live_chats.open(Note(Feed()), broker)
        other = live_chats.open(Note(Feed()), Broker())
        await other.__anext__()
        await other.aclose()
        await streams[0].aclose()
        again = live_chats.open(Note(Feed()), broker)
        await again.__anext__()
        for stream in [*streams[1:], again]:
            await stream.aclose()
        return refused.value

    refused = asyncio.run(run())
    assert refused.status == 503 and refused.headers["Retry-After"] == "60"
    assert not live_chats._streams


def test_streams_are_capped_per_process(monkeypatch):
    monkeypatch.setattr(live_chats, "MAX_STREAMS", 1)

    async def run():
        first = live_chats.open(Note(Feed()), Broker())
        await first.__anext__()
        with pytest.raises(ServiceError):
            live_chats.open(Note(Feed()), Broker())
        await first.aclose()

    asyncio.run(run())


def test_a_stream_opened_but_never_read_holds_no_place():
    feed = Feed()

    async def run():
        live_chats.open(Note(feed), Broker())

    asyncio.run(run())
    assert not live_chats._streams


def test_the_caller_leaving_closes_the_feed(client, monkeypatch):
    # A real server and a real disconnect: `listen()` stops only on close(), so this is what stops a Teams connection leaking.
    monkeypatch.setattr(live_chats, "HEARTBEAT", 0.2)
    feed = Feed([event("connected", None)])
    client(feed)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        with httpx.stream("GET", f"http://127.0.0.1:{port}/api/chats/live", headers=H, timeout=10) as response:
            lines = response.iter_lines()
            assert json.loads(next(lines)) == {"kind": "ping"}
            assert json.loads(next(lines)) == {"kind": "connected"}
            assert not feed.closed.is_set()
        assert feed.closed.wait(10), "the feed stayed open after the caller left"
    finally:
        server.should_exit = True
        thread.join(10)
    deadline = time.monotonic() + 5
    while live_chats._streams and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not live_chats._streams
