import asyncio

from src.application.abstractions.i_graph_client_factory import IGraphClientFactory
from src.application.abstractions.i_profile_reader import IProfileReader
from src.application.dtos.linked_identity import LinkedIdentity


class LinkedIdentityReader:
    """Who a new refresh token belongs to; empty when that can't be read."""

    def __init__(self, clients: IGraphClientFactory, profile: IProfileReader):
        self._clients = clients
        self._profile = profile

    async def read(self, refresh_token: str) -> LinkedIdentity:
        try:
            note, broker = self._clients.build_client(refresh_token)
            me = await asyncio.to_thread(self._profile.get, note, broker)
            return LinkedIdentity(id=me.get("id"), email=me.get("mail") or me.get("userPrincipalName"), name=me.get("displayName"))
        except Exception:
            return LinkedIdentity()
