from abc import ABC, abstractmethod

from src.application.abstractions.i_account_broker import IAccountBroker
from src.application.abstractions.i_graph_client import IGraphClient


class IPeoplePhotos(ABC):
    """Profile photos by e-mail address and by user id."""

    @abstractmethod
    def photo(self, note: IGraphClient, broker: IAccountBroker, email: str, size: int) -> bytes | None: ...

    @abstractmethod
    def user_photo(self, note: IGraphClient, user_id: str, size: int) -> bytes | None: ...
