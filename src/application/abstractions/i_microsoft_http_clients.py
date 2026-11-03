from abc import ABC, abstractmethod
from collections.abc import Iterator


class IMicrosoftHttpClients(ABC):
    """The shared keep-alive HTTP clients, their warm-up and their shutdown."""

    @abstractmethod
    def download_client(self): ...

    @abstractmethod
    def stream_download(self, url: str, limit: int, follow_redirects: bool = True) -> Iterator[bytes]: ...

    @abstractmethod
    async def post_form(self, url: str, data: dict, client=None) -> dict: ...

    @abstractmethod
    async def warm_up(self) -> None: ...

    @abstractmethod
    async def close_shared_client(self) -> None: ...
