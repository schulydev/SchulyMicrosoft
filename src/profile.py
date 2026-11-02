"""The signed-in user's own profile (`GET /me`), cached per account.

Graph throttles `/me` (a directory read) with long Retry-After waits that OutNote sleeps in the
worker thread, so the profile is read at most once per account per hour.
"""

from src.account_cache import for_broker

CACHE_KEY = "me_profile"
TTL = 3600.0


def get(note, broker) -> dict:
    cache = for_broker(broker)
    hit = cache.get(CACHE_KEY)
    if hit is not None:
        return hit
    with cache.lock(CACHE_KEY):
        hit = cache.get(CACHE_KEY)
        if hit is None:
            hit = note.me()
            cache.set(CACHE_KEY, hit, TTL)
        return hit
