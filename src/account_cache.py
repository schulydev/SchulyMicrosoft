"""A small TTL store per linked account.

It lives on the account's shared broker (see `outnote_client._SharedBroker`), so it follows the
account across refresh-token rotation and is evicted together with the broker. Nothing in it is
persisted; it only spares repeat Microsoft calls for data that rarely changes.
"""

import threading
import time

MAX_ITEMS = 2000


class AccountCache:
    def __init__(self, max_items: int = MAX_ITEMS):
        self._max = max_items
        self._items: dict[object, tuple[object, float]] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def get(self, key, default=None):
        with self._guard:
            hit = self._items.get(key)
            if hit is None:
                return default
            value, expires = hit
            if expires <= time.monotonic():
                del self._items[key]
                return default
            return value

    def has(self, key) -> bool:
        marker = object()
        return self.get(key, marker) is not marker

    def set(self, key, value, ttl: float):
        with self._guard:
            self._items.pop(key, None)
            self._items[key] = (value, time.monotonic() + ttl)
            if len(self._items) > self._max:
                now = time.monotonic()
                for k in [k for k, (_, exp) in self._items.items() if exp <= now]:
                    del self._items[k]
                while len(self._items) > self._max:
                    del self._items[next(iter(self._items))]

    def discard(self, match):
        """Drops every entry whose key `match` accepts (a write made them stale)."""
        with self._guard:
            for key in [k for k in self._items if match(k)]:
                del self._items[key]

    def lock(self, name: str) -> threading.Lock:
        """A lock per name, so concurrent misses for the same value fetch it once."""
        with self._guard:
            return self._locks.setdefault(name, threading.Lock())


_attach = threading.Lock()


def for_broker(broker) -> AccountCache:
    """The broker's cache, attached on first use (a broker built elsewhere gets one too)."""
    cache = getattr(broker, "cache", None)
    if cache is None:
        with _attach:
            cache = getattr(broker, "cache", None)
            if cache is None:
                cache = AccountCache()
                broker.cache = cache
    return cache
