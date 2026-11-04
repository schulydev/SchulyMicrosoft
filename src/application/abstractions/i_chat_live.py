from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from src.application.abstractions.i_account_broker import IAccountBroker
from src.application.abstractions.i_graph_client import IGraphClient


class IChatLive(ABC):
    """Live chat events as NDJSON lines, for as long as the caller reads them."""

    @abstractmethod
    def open(self, note: IGraphClient, broker: IAccountBroker) -> AsyncIterator[bytes]: ...
