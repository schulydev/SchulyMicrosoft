from abc import ABC, abstractmethod

from src.application.abstractions.i_account_broker import IAccountBroker
from src.application.abstractions.i_graph_client import IGraphClient


class IFileThumbnails(ABC):
    """File kinds, the share-link host check, and thumbnails."""

    SIZES: tuple[str, ...]

    @abstractmethod
    def is_share_url(self, url) -> bool: ...

    @abstractmethod
    def file_kind(self, name, mime) -> str: ...

    @abstractmethod
    def has_thumbnail(self, url, kind: str) -> bool: ...

    @abstractmethod
    def image_type(self, head: bytes) -> str | None: ...

    @abstractmethod
    def safe_graph_id(self, value) -> bool: ...

    @abstractmethod
    def chat_file_thumbnail(self, note: IGraphClient, broker: IAccountBroker, url: str, size: str) -> bytes | None: ...

    @abstractmethod
    def drive_item_thumbnail(self, note: IGraphClient, item_id: str, size: str, drive_id: str | None = None) -> bytes | None: ...
