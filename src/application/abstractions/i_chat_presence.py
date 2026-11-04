from abc import ABC, abstractmethod

from src.application.abstractions.i_account_broker import IAccountBroker
from src.application.abstractions.i_graph_client import IGraphClient


class IChatPresence(ABC):
    """The Teams status of the other person in a 1:1 chat."""

    @abstractmethod
    def of_chat(self, note: IGraphClient, broker: IAccountBroker, chat_id: str) -> dict: ...
