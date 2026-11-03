from abc import ABC, abstractmethod

from src.application.abstractions.i_account_broker import IAccountBroker
from src.application.abstractions.i_graph_client import IGraphClient


class ITeamsFiles(ABC):
    """Teams, channels, drive items, shared and recent files, and download links."""

    MAX_DOWNLOAD_BYTES: int
    MAX_PATH_CHARS: int

    @abstractmethod
    def valid_path(self, path) -> list[str]: ...

    @abstractmethod
    def is_download_url(self, url) -> bool: ...

    @abstractmethod
    def fetch_bytes(self, url: str, cap: int) -> bytes: ...

    @abstractmethod
    def download_link(self, note: IGraphClient, path: str, item: dict) -> str: ...

    @abstractmethod
    def item_base(self, drive_id: str | None, item_id: str) -> str: ...

    @abstractmethod
    def joined_teams(self, note: IGraphClient, broker: IAccountBroker) -> list[dict]: ...

    @abstractmethod
    def channels(self, note: IGraphClient, broker: IAccountBroker, team_id: str) -> list[dict]: ...

    @abstractmethod
    def team_drive_id(self, note: IGraphClient, broker: IAccountBroker, team_id: str) -> str: ...

    @abstractmethod
    def own_drive_id(self, note: IGraphClient, broker: IAccountBroker) -> str | None: ...

    @abstractmethod
    def team_files(self, note: IGraphClient, broker: IAccountBroker, team_id: str, channel_id: str | None, path: str | None, top: int) -> dict: ...

    @abstractmethod
    def drive_item(self, note: IGraphClient, drive_id: str, item_id: str) -> dict: ...

    @abstractmethod
    def children(self, note: IGraphClient, drive_id: str, item_id: str, top: int) -> list[dict]: ...

    @abstractmethod
    def shared_with_me(self, note: IGraphClient, top: int) -> list[dict]: ...

    @abstractmethod
    def recent(self, note: IGraphClient, top: int) -> list[dict]: ...
