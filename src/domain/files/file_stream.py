from collections.abc import Iterator
from dataclasses import dataclass


@dataclass
class FileStream:
    """Bytes that stream through without being held."""

    chunks: Iterator[bytes]
    content_type: str
    file_name: str
