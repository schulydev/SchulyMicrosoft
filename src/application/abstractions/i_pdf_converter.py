from abc import ABC, abstractmethod
from typing import BinaryIO

from src.application.abstractions.i_account_broker import IAccountBroker
from src.application.abstractions.i_graph_client import IGraphClient


class IPdfConverter(ABC):
    """Office files as PDF, converted by Microsoft 365. Each answer is a spooled file positioned at 0."""

    @abstractmethod
    def is_convertible(self, name) -> bool: ...

    @abstractmethod
    def drive_item_pdf(self, note: IGraphClient, item_id: str, drive_id: str | None = None) -> BinaryIO: ...

    @abstractmethod
    def bytes_pdf(self, note: IGraphClient, broker: IAccountBroker, data: bytes, name: str) -> BinaryIO: ...
