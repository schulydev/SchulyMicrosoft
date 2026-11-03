from dataclasses import dataclass
from typing import BinaryIO


@dataclass
class SpooledPdf:
    """A converted PDF in a spooled temporary file, positioned at 0, and the name of the file it came from."""

    source_name: str | None
    file: BinaryIO
