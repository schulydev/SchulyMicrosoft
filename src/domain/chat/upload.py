from dataclasses import dataclass
from typing import BinaryIO


@dataclass
class Upload:
    name: str
    file: BinaryIO
    size: int
    content_type: str | None = None
