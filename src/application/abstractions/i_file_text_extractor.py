from abc import ABC, abstractmethod


class IFileTextExtractor(ABC):
    """Plain text out of a file's bytes."""

    MAX_SOURCE_BYTES: int

    @abstractmethod
    def kind_of(self, name) -> str | None: ...

    @abstractmethod
    def extract(self, name: str, data: bytes, offset: int = 0, max_chars: int = 20000, sheet: str | None = None, row_offset: int = 0, max_rows: int = 500, notes: list[str] | None = None) -> dict: ...
