"""Profile photos by e-mail address, for mail senders (which come with an address, not a user id).

Graph accepts a UPN in `users/{id}`, and UPN and mail are usually equal, so the address is tried
directly first; when that 404s, the user is resolved with `users?$filter=mail eq '...'`. A person
outside the tenant resolves to nobody and reads as no photo. Results are cached per account: a
photo for 6 hours, a miss for 30 minutes.
"""

from urllib.parse import quote
from outnote import GraphError

from src.application.abstractions.i_people_photos import IPeoplePhotos
from src.domain.errors.photo_throttled import PhotoThrottled
from src.infrastructure.microsoft.account_cache import AccountCache


class PeoplePhotos(IPeoplePhotos):
    """Profile photos by e-mail address (mail senders) and by user id."""

    HIT_TTL = 6 * 3600
    MISS_TTL = 30 * 60
    MAX_CACHED_BYTES = 200 * 1024

    def _odata_string(self, value: str) -> str:
        return value.replace("'", "''")

    def _first(self, note, user: str, size: int) -> bytes | None:
        seg = quote(user, safe="@")
        for path in (f"users/{seg}/photos/{size}x{size}/$value", f"users/{seg}/photo/$value"):
            try:
                return note.get(path, raw="bytes")
            except GraphError as ex:
                if ex.status == 429:
                    raise PhotoThrottled(ex.retry_after) from None
                if ex.status not in (400, 404):
                    raise
        return None

    def _resolve(self, note, email: str) -> str | None:
        try:
            found = note.list("users", {"$filter": f"mail eq '{self._odata_string(email)}'", "$select": "id", "$top": 1}, limit=1)
        except GraphError as ex:
            if ex.status == 429:
                raise PhotoThrottled(ex.retry_after) from None
            if ex.status in (400, 403, 404):
                return None
            raise
        return found[0].get("id") if found else None

    def user_photo(self, note, user_id: str, size: int) -> bytes | None:
        for path in (f"users/{user_id}/photos/{size}x{size}/$value", f"users/{user_id}/photo/$value"):
            try:
                return note.get(path, raw="bytes")
            except GraphError as ex:
                if ex.status != 404:
                    raise
        return None

    def photo(self, note, broker, email: str, size: int) -> bytes | None:
        email = email.strip().lower()
        cache = AccountCache.for_broker(broker)
        key = ("people_photo", email, size)
        marker = object()
        hit = cache.get(key, marker)
        if hit is not marker:
            return hit
        data = self._first(note, email, size)
        if data is None:
            user_id = self._resolve(note, email)
            if user_id:
                data = self._first(note, user_id, size)
        if data is None:
            cache.set(key, None, self.MISS_TTL)
        elif len(data) <= self.MAX_CACHED_BYTES:
            cache.set(key, data, self.HIT_TTL)
        return data
