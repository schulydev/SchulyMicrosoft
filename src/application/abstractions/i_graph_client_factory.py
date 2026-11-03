from abc import ABC, abstractmethod

from src.application.abstractions.i_account_broker import IAccountBroker
from src.application.abstractions.i_graph_client import IGraphClient


class IGraphClientFactory(ABC):
    """The account's client and broker for a refresh token. Both are shared by every request that carries that token."""

    @abstractmethod
    def build_client(self, refresh_token: str) -> tuple[IGraphClient, IAccountBroker]: ...
