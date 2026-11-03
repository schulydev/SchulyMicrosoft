import hashlib
import threading
from collections import OrderedDict

from src.infrastructure.microsoft.shared_broker import SharedBroker


class BrokerCache:
    """In-memory LRU of brokers keyed by SHA-256 of the refresh token (the raw token is never a key)."""

    BROKER_CACHE_SIZE = 1000

    def __init__(self, max_size: int = BROKER_CACHE_SIZE):
        self._max = max_size
        self._items: OrderedDict[str, SharedBroker] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def _key(refresh_token: str) -> str:
        return hashlib.sha256(refresh_token.encode()).hexdigest()

    def get(self, refresh_token: str) -> SharedBroker:
        key = self._key(refresh_token)
        with self._lock:
            broker = self._items.get(key)
            if broker is None:
                broker = SharedBroker(refresh_token, self._register)
                self._store(key, broker)
            else:
                self._items.move_to_end(key)
            return broker

    def _register(self, refresh_token: str, broker: SharedBroker):
        with self._lock:
            self._store(self._key(refresh_token), broker)

    def _store(self, key: str, broker: SharedBroker):
        self._items[key] = broker
        self._items.move_to_end(key)
        while len(self._items) > self._max:
            self._items.popitem(last=False)

    def clear(self):
        with self._lock:
            self._items.clear()
