"""Profile photos by e-mail address, for mail senders (which come with an address, not a user id).

Graph accepts a UPN in `users/{id}`, and UPN and mail are usually equal, so the address is tried
directly first; when that 404s, the user is resolved with `users?$filter=mail eq '...'`. A person
outside the tenant resolves to nobody and reads as no photo. Results are cached per account: a
photo for 6 hours, a miss for 30 minutes.
"""

from urllib.parse import quote

from outnote import GraphError

from src.account_cache import for_broker

HIT_TTL = 6 * 3600
MISS_TTL = 30 * 60
MAX_CACHED_BYTES = 200 * 1024


class Throttled(RuntimeError):
    pass


def _odata_string(value: str) -> str:
    return value.replace("'", "''")


def _first(note, user: str, size: int) -> bytes | None:
    seg = quote(user, safe="@")
    for path in (f"users/{seg}/photos/{size}x{size}/$value", f"users/{seg}/photo/$value"):
        try:
            return note.get(path, raw="bytes")
        except GraphError as ex:
            if ex.status == 429:
                raise Throttled() from None
            if ex.status not in (400, 404):
                raise
    return None


def _resolve(note, email: str) -> str | None:
    try:
        found = note.list("users", {"$filter": f"mail eq '{_odata_string(email)}'", "$select": "id", "$top": 1}, limit=1)
    except GraphError as ex:
        if ex.status == 429:
            raise Throttled() from None
        if ex.status in (400, 403, 404):
            return None
        raise
    return found[0].get("id") if found else None


def photo(note, broker, email: str, size: int) -> bytes | None:
    email = email.strip().lower()
    cache = for_broker(broker)
    key = ("people_photo", email, size)
    marker = object()
    hit = cache.get(key, marker)
    if hit is not marker:
        return hit
    data = _first(note, email, size)
    if data is None:
        user_id = _resolve(note, email)
        if user_id:
            data = _first(note, user_id, size)
    if data is None:
        cache.set(key, None, MISS_TTL)
    elif len(data) <= MAX_CACHED_BYTES:
        cache.set(key, data, HIT_TTL)
    return data
