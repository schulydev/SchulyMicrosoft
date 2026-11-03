"""The signed-in user's own profile (`GET /me`), cached per account, never stalled by throttling.

Graph throttles `/me` (a directory read) on its own, with 429 and Retry-After ~21 s, even when every
other route answers at once. OutNote sleeps each Retry-After in the worker thread and retries up to
4 times, which made the first `/api/me` after a start take 42 s (two 21 s waits). So `/me` is asked
exactly once, without OutNote's retries; on 429 (or any failure) the profile comes from the claims of
the access token the broker just minted (oid, name, upn), which Microsoft signed for this user. A
`/me` answer is kept for an hour, a profile from claims for five minutes, so `/me` is tried again later.
"""

import base64
import binascii
import json
import logging
from entrance import HTTPError, http_client
from outnote import C_OFFICE, GraphError

from src.application.abstractions.i_profile_reader import IProfileReader
from src.infrastructure.microsoft.account_cache import AccountCache


class ProfileReader(IProfileReader):
    """The signed-in user's /me profile: one try without retries, the token's claims on failure, cached per account."""

    log = logging.getLogger("schuly.microsoft")
    CACHE_KEY = "me_profile"
    TTL = 3600.0
    CLAIMS_TTL = 300.0
    ME_URL = "https://graph.microsoft.com/v1.0/me"
    ME_TIMEOUT = 10.0
    http_client = staticmethod(http_client)

    def get(self, note, broker) -> dict:
        cache = AccountCache.for_broker(broker)
        hit = cache.get(self.CACHE_KEY)
        if hit is not None:
            return hit
        with cache.lock(self.CACHE_KEY):
            hit = cache.get(self.CACHE_KEY)
            if hit is None:
                hit, ttl = self._fetch(note, broker)
                cache.set(self.CACHE_KEY, hit, ttl)
            return hit

    def _fetch(self, note, broker) -> tuple[dict, float]:
        token = broker(C_OFFICE)
        status = None
        try:
            r = self.http_client().request("GET", self.ME_URL, headers={"Authorization": f"Bearer {token}"}, timeout=self.ME_TIMEOUT)
            status = r.status_code
            if status == 200:
                return r.json(), self.TTL
            self.log.info("/me answered %s (Retry-After %s); using the token's claims", status, r.headers.get("Retry-After"))
        except (*HTTPError, ValueError) as ex:  # entrance's HTTPError is a tuple, so it is unpacked
            self.log.info("/me failed (%s); using the token's claims", type(ex).__name__)
        claims = self.from_claims(token)
        if claims is None:
            raise GraphError(status or 502, "The profile is unavailable.")
        return claims, self.CLAIMS_TTL

    def from_claims(self, access_token: str) -> dict | None:
        """A `/me`-shaped profile from the access token's claims, or None when it carries no user object id."""
        try:
            payload = access_token.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        except (IndexError, ValueError, binascii.Error):
            return None
        if not isinstance(claims, dict) or not isinstance(claims.get("oid"), str):
            return None
        upn = claims.get("upn") or claims.get("unique_name") or claims.get("preferred_username")
        return {
            "id": claims["oid"],
            "displayName": claims.get("name"),
            "givenName": claims.get("given_name"),
            "surname": claims.get("family_name"),
            "userPrincipalName": upn,
            "mail": claims.get("email") or upn,
        }
