from abc import ABC, abstractmethod


class IRequestBody(ABC):
    """The raw request body of an upload, read only after the request passed its checks."""

    @property
    @abstractmethod
    def declared_length(self) -> str | None: ...

    @abstractmethod
    async def read(self, cap: int) -> bytes:
        """The whole body, refused past `cap` bytes whatever the declared length claims."""
