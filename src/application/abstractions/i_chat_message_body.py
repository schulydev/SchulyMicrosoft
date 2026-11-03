from abc import ABC, abstractmethod

from src.domain.chat.upload import Upload


class IChatMessageBody(ABC):
    """The body of a chat send: JSON, or multipart/form-data with `images` and `files` parts."""

    @property
    @abstractmethod
    def is_multipart(self) -> bool: ...

    @property
    @abstractmethod
    def declared_length(self) -> str | None: ...

    @abstractmethod
    async def read(self, cap: int) -> tuple[dict, list[Upload], list[Upload]]:
        """(fields, images, files), refused past `cap` bytes whatever the declared length claims."""

    @abstractmethod
    async def close(self) -> None:
        """Deletes any spooled file parts."""
