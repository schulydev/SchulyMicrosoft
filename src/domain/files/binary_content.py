from dataclasses import dataclass


@dataclass
class BinaryContent:
    """Bytes held in memory, with the type to serve them as and, for a download, the file name."""

    data: bytes
    content_type: str
    file_name: str | None = None
