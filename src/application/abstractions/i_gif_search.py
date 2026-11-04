from abc import ABC, abstractmethod

from src.application.abstractions.i_account_broker import IAccountBroker


class IGifSearch(ABC):
    """GIF search, spent per account."""

    @abstractmethod
    def allow(self, broker: IAccountBroker) -> bool: ...

    @abstractmethod
    def search(self, broker: IAccountBroker, query: str | None, limit: int) -> list[dict]: ...
