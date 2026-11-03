from dataclasses import dataclass, field

from src.domain.chat.upload import Upload


@dataclass
class OutgoingMessage:
    content: str = ""
    content_type: str = "text"
    importance: str | None = None
    mentions: list[dict] = field(default_factory=list)
    gif: dict | None = None
    images: list[Upload] = field(default_factory=list)
    files: list[Upload] = field(default_factory=list)
