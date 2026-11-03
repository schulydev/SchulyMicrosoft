import re
from urllib.parse import quote

from src.domain.errors.service_error import ServiceError


class GraphIds:
    """The one validator for ids that become upstream path segments, and their patterns."""

    CHAT_ID_PATTERN = re.compile(r"[A-Za-z0-9:@._=-]{1,300}")
    USER_ID_PATTERN = re.compile(r"[A-Za-z0-9@._-]{1,200}")
    SCHULY_USER_ID_PATTERN = re.compile(r"[A-Za-z0-9._:@-]{1,128}")
    GRAPH_ID_PATTERN = re.compile(r"[A-Za-z0-9=_\-+/.]{1,512}")
    MESSAGE_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")
    ATTACHMENT_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,100}")
    DOCUMENT_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,120}")
    DRIVE_ITEM_PATTERN = re.compile(r"[A-Za-z0-9!=_\-+.]{1,512}")
    TEAM_ID_PATTERN = re.compile(r"[0-9a-fA-F-]{36}")
    CHANNEL_ID_PATTERN = re.compile(r"19:[A-Za-z0-9_-]{1,200}@thread\.(tacv2|skype)")
    DRIVE_ID_PATTERN = re.compile(r"[A-Za-z0-9!_-]{1,200}")
    CHANNEL_MESSAGE_ID_PATTERN = re.compile(r"[0-9]{1,20}")

    @classmethod
    def check(cls, value: str, pattern: re.Pattern, name: str) -> None:
        """The pattern, and no dot segment ("." / ".." collapse in URL handling and retarget the call)."""
        if not pattern.fullmatch(value) or cls.has_dot_segment(value):
            raise ServiceError(400, f"Invalid {name}.")

    @staticmethod
    def has_dot_segment(value: str) -> bool:
        return ".." in value or any(part == "." for part in re.split(r"[/\\]", value))

    @staticmethod
    def seg(value: str) -> str:
        # OutNote does not escape path segments; ids may hold "+" or "/", so percent-encode them for Graph.
        return quote(value, safe="")
