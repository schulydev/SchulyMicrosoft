from abc import ABC, abstractmethod

from src.application.abstractions.i_account_broker import IAccountBroker
from src.application.abstractions.i_graph_client import IGraphClient


class IChatReader(ABC):
    """Graph chat messages made ready for the web."""

    @abstractmethod
    def enrich(self, note: IGraphClient, broker: IAccountBroker, messages: list[dict], chat_id: str | None = None) -> list[dict]: ...

    @abstractmethod
    def file_ref(self, note: IGraphClient, broker: IAccountBroker, chat_id: str, message_id: str, attachment_id: str) -> dict | None: ...
