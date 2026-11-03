from abc import ABC, abstractmethod

from src.application.abstractions.i_account_broker import IAccountBroker
from src.application.abstractions.i_graph_client import IGraphClient


class IProfileReader(ABC):
    """The signed-in user's profile. `/me` is read only through this."""

    @abstractmethod
    def get(self, note: IGraphClient, broker: IAccountBroker) -> dict: ...
