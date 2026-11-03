import threading
from collections.abc import Callable

from entrance import Broker
from outnote import OutNote

from src.application.abstractions.i_account_broker import IAccountBroker
from src.application.abstractions.i_graph_client import IGraphClient
from src.infrastructure.microsoft.account_cache import AccountCache

IGraphClient.register(OutNote)
IAccountBroker.register(Broker)


class SharedBroker(Broker):
    """A Broker shared by every request that carries the same refresh token.

    Entrance's Broker already keeps one access token per (client id, scope) and only redeems the
    refresh token (which makes Microsoft rotate it) when that entry is missing or within 60s of
    expiry. The Broker used to be rebuilt per request, so every call redeemed. Sharing it means
    repeat calls reuse the minted access tokens and the refresh token stays unchanged. The lock makes
    concurrent misses redeem once instead of racing; `on_rotate` re-registers the broker under the
    new token's hash so the caller's next request (which sends the rotated token) still hits.

    It also owns the account's one OutNote client, as OutNote recommends for long-lived use: the ids that client keeps in
    memory (user, tenant) belong to this account and live and die with this broker, so accounts never share one."""

    def __init__(self, refresh_token: str, on_rotate: Callable[[str, "SharedBroker"], None]):
        super().__init__(refresh_token)
        self._lock = threading.Lock()
        self._on_rotate = on_rotate
        # Per-account values that rarely change (folder roles, chat pictures); shared with the broker's lifetime.
        self.cache = AccountCache()
        self.note = OutNote(self)

    def __call__(self, client_id, scope="https://graph.microsoft.com/.default"):
        with self._lock:
            before = self.refresh_token
            token = super().__call__(client_id, scope)
            if self.refresh_token != before:
                self._on_rotate(self.refresh_token, self)
            return token
