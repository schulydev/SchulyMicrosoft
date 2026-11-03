import threading
import time
from collections import deque


class RateLimiter:
    """Sliding-window counter keyed by an opaque string (never the raw account name)."""

    def __init__(self):
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window: float) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] > window:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            return True

    def add(self, key: str):
        with self._lock:
            self._hits.setdefault(key, deque()).append(time.monotonic())

    def count(self, key: str, window: float) -> int:
        now = time.monotonic()
        with self._lock:
            hits = self._hits.get(key)
            if not hits:
                return 0
            while hits and now - hits[0] > window:
                hits.popleft()
            return len(hits)

    def sweep(self, window: float = 600):
        now = time.monotonic()
        with self._lock:
            for key in [k for k, h in self._hits.items() if not h or now - h[-1] > window]:
                del self._hits[key]
