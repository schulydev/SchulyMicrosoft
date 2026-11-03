import os
from dataclasses import dataclass


@dataclass
class EmojiOptions:
    """The Teams emoji asset version to start from."""

    DEFAULT_VERSION = "0f52465a47bf42f299c74a639443f33e"

    version: str

    @classmethod
    def from_environment(cls) -> "EmojiOptions":
        return cls(version=os.getenv("TEAMS_EMOTICON_VERSION", cls.DEFAULT_VERSION))
