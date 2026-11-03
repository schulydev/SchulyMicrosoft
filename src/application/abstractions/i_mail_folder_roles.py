from abc import ABC, abstractmethod

from src.application.abstractions.i_account_broker import IAccountBroker
from src.application.abstractions.i_graph_client import IGraphClient


class IMailFolderRoles(ABC):
    """Well-known mail folder names by folder id."""

    @abstractmethod
    def lookup(self, note: IGraphClient) -> dict[str, str]: ...

    @abstractmethod
    def cached(self, broker: IAccountBroker) -> dict[str, str] | None: ...

    @abstractmethod
    def remember(self, broker: IAccountBroker, roles: dict[str, str]) -> None: ...
