from abc import ABC, abstractmethod
from collections.abc import Callable

from src.domain.files.file_stream import FileStream


class IMicrosoftHttpClients(ABC):
    """The shared keep-alive HTTP clients, their warm-up and their shutdown."""

    @abstractmethod
    def download_client(self): ...

    @abstractmethod
    def open_download(self, url: str, limit: int, allowed: Callable[[str], bool], content_type: str, file_name: str, byte_range: str | None = None) -> FileStream: ...

    @abstractmethod
    async def post_form(self, url: str, data: dict, client=None) -> dict: ...

    @abstractmethod
    async def warm_up(self) -> None: ...

    @abstractmethod
    async def close_shared_client(self) -> None: ...
