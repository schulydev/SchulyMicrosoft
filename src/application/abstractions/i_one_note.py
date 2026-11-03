from abc import ABC, abstractmethod

from src.application.abstractions.i_account_broker import IAccountBroker
from src.application.abstractions.i_graph_client import IGraphClient


class IOneNote(ABC):
    """OneNote over Graph."""

    ID_PATTERN: object

    @abstractmethod
    def is_id(self, value: str) -> bool: ...

    @abstractmethod
    def notebooks(self, note: IGraphClient, broker: IAccountBroker, teams: bool = True) -> list[dict]: ...

    @abstractmethod
    def tree(self, note: IGraphClient, broker: IAccountBroker, notebook: str) -> dict: ...

    @abstractmethod
    def pages(self, note: IGraphClient, section: str, top: int, skip: int) -> dict: ...

    @abstractmethod
    def page(self, note: IGraphClient, page_scoped: str) -> dict: ...

    @abstractmethod
    def create_page(self, note: IGraphClient, broker: IAccountBroker, section: str, title: str, body: str | None) -> dict: ...

    @abstractmethod
    def update_page(self, note: IGraphClient, broker: IAccountBroker, page_scoped: str, title: str | None, outlines: list[dict] | None, append: str | None) -> dict: ...

    @abstractmethod
    def delete_page(self, note: IGraphClient, broker: IAccountBroker, page_scoped: str) -> None: ...

    @abstractmethod
    def resource(self, broker: IAccountBroker, resource_scoped: str, limit: int) -> bytes: ...

    @abstractmethod
    def search(self, note: IGraphClient, broker: IAccountBroker, query: str, notebook: str | None, top: int) -> dict: ...
