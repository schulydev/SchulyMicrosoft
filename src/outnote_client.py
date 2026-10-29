"""Thin, stateless wrapper over OutNote / Entrance.

The device-code sign-in is two documented OAuth calls (start + poll). Data reads
build an OutNote client from the caller's FOCI refresh token, which the broker may
rotate; callers get the rotated token back and own its persistence. Nothing here is
stored server-side.
"""

import asyncio
import hashlib
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable

import entrance
import httpx
from entrance import Broker
from outnote import OutNote

from src import config

log = logging.getLogger("schuly.microsoft")


class MicrosoftError(Exception):
    def __init__(self, error: str, description: str = ""):
        self.error = error
        super().__init__(f"{error}: {description}" if description else error)


async def start_device_login(client: httpx.AsyncClient | None = None) -> dict:
    """Begin the device-code flow: returns user_code, verification_uri and the device_code to poll with."""
    data = await _post(config.DEVICECODE_URL, {"client_id": config.DEVICE_CLIENT_ID, "scope": config.DEVICE_SCOPE}, client)
    if not data.get("device_code"):
        raise MicrosoftError(data.get("error", "no_device_code"), data.get("error_description", "the client may not support the device flow"))
    return data


async def poll_device_login(device_code: str, client: httpx.AsyncClient | None = None) -> dict:
    """Poll once. Returns the raw token response: access_token + refresh_token, or error=authorization_pending."""
    return await _post(config.TOKEN_URL, {"grant_type": config.DEVICE_GRANT, "client_id": config.DEVICE_CLIENT_ID, "device_code": device_code}, client)


BROKER_CACHE_SIZE = 1000


class _SharedBroker(Broker):
    """A Broker shared by every request that carries the same refresh token.

    Entrance's Broker already keeps one access token per (client id, scope) and only redeems the
    refresh token (which makes Microsoft rotate it) when that entry is missing or within 60s of
    expiry. The Broker used to be rebuilt per request, so every call redeemed. Sharing it means
    repeat calls reuse the minted access tokens and the refresh token stays unchanged. The lock makes
    concurrent misses redeem once instead of racing; `on_rotate` re-registers the broker under the
    new token's hash so the caller's next request (which sends the rotated token) still hits."""

    def __init__(self, refresh_token: str, on_rotate: Callable[[str, "_SharedBroker"], None]):
        super().__init__(refresh_token)
        self._lock = threading.Lock()
        self._on_rotate = on_rotate

    def __call__(self, client_id, scope="https://graph.microsoft.com/.default"):
        with self._lock:
            before = self.refresh_token
            token = super().__call__(client_id, scope)
            if self.refresh_token != before:
                self._on_rotate(self.refresh_token, self)
            return token


class _BrokerCache:
    """In-memory LRU of brokers keyed by SHA-256 of the refresh token (the raw token is never a key)."""

    def __init__(self, max_size: int = BROKER_CACHE_SIZE):
        self._max = max_size
        self._items: OrderedDict[str, _SharedBroker] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def _key(refresh_token: str) -> str:
        return hashlib.sha256(refresh_token.encode()).hexdigest()

    def get(self, refresh_token: str) -> _SharedBroker:
        key = self._key(refresh_token)
        with self._lock:
            broker = self._items.get(key)
            if broker is None:
                broker = _SharedBroker(refresh_token, self._register)
                self._store(key, broker)
            else:
                self._items.move_to_end(key)
            return broker

    def _register(self, refresh_token: str, broker: _SharedBroker):
        with self._lock:
            self._store(self._key(refresh_token), broker)

    def _store(self, key: str, broker: _SharedBroker):
        self._items[key] = broker
        self._items.move_to_end(key)
        while len(self._items) > self._max:
            self._items.popitem(last=False)

    def clear(self):
        with self._lock:
            self._items.clear()


_brokers = _BrokerCache()


def build_client(refresh_token: str) -> tuple[OutNote, Broker]:
    """An OutNote client over a shared per-token broker; read `broker.refresh_token` after use for the (possibly rotated) value."""
    broker = _brokers.get(refresh_token)
    return OutNote(broker), broker


_async_client: httpx.AsyncClient | None = None


def _http2() -> bool:
    try:
        import h2  # noqa: F401
    except ImportError:
        return False
    return True


def shared_async_client() -> httpx.AsyncClient:
    """One keep-alive client for the sign-in calls (connect bounded to 5 s, connect retries)."""
    global _async_client
    if _async_client is None:
        _async_client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=5.0),
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=10, keepalive_expiry=60),
            transport=httpx.AsyncHTTPTransport(retries=3, http2=_http2()),
        )
    return _async_client


async def close_shared_client():
    global _async_client
    client, _async_client = _async_client, None
    if client is not None:
        await client.aclose()


async def warm_up():
    """Open connections to Microsoft's login and Graph hosts so the first real call skips DNS, TCP and TLS."""
    await asyncio.to_thread(entrance.warm_up, [config.TOKEN_URL, "https://graph.microsoft.com/v1.0/"])


async def _post(url: str, data: dict, client: httpx.AsyncClient | None) -> dict:
    client = client or shared_async_client()
    started = time.perf_counter()
    try:
        response = await client.post(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
        return response.json()
    finally:
        log.debug("POST %s took %.0f ms", url, (time.perf_counter() - started) * 1000)


# Read helpers, kept tiny so routers stay declarative. Each returns plain JSON-able data.
def read(outnote: OutNote, action: Callable[[OutNote], object]) -> object:
    return action(outnote)
