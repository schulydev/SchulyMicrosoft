from abc import ABC, abstractmethod
from collections.abc import Callable

from src.application.abstractions.i_account_broker import IAccountBroker
from src.application.abstractions.i_graph_client import IGraphClient


class IAccountRunner(ABC):
    """Runs blocking work for an account off the event loop and turns what Microsoft answers into the service's refusals."""

    @abstractmethod
    async def run(self, refresh_token: str, action: Callable[[IGraphClient, IAccountBroker], object]) -> object: ...
