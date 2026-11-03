from abc import ABC, abstractmethod

from src.application.abstractions.i_account_broker import IAccountBroker
from src.application.abstractions.i_graph_client import IGraphClient


class IGraphSearch(ABC):
    """Search over files, mail, chats and channel posts. The query never reaches a log."""

    @abstractmethod
    def run(self, note: IGraphClient, broker: IAccountBroker, q: str, types: list[str], start: int, size: int, team_id: str | None = None) -> dict: ...
