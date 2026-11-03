from abc import ABC, abstractmethod
from collections.abc import Callable

from src.application.abstractions.i_account_broker import IAccountBroker
from src.application.abstractions.i_graph_client import IGraphClient


class IOneNoteRunner(ABC):
    """`IAccountRunner` for OneNote: refusals OneNote gives as such keep their meaning instead of becoming a 502."""

    @abstractmethod
    async def run(self, refresh_token: str, action: Callable[[IGraphClient, IAccountBroker], object]) -> object: ...
