from collections.abc import Iterator
from dataclasses import dataclass


@dataclass
class FileStream:
    """Bytes that stream through without being held. A range answer carries status 206 and its `content_range`; `content_length` is what this answer's body holds, when known."""

    chunks: Iterator[bytes]
    content_type: str
    file_name: str
    status_code: int = 200
    content_length: int | None = None
    content_range: str | None = None
