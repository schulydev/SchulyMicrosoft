from abc import ABC, abstractmethod

from src.domain.chat.catalogue import Catalogue


class IEmojiCatalogue(ABC):
    """Teams' emoji: the catalogue, what may be sent, and what a message body holds."""

    @abstractmethod
    def normalize_locale(self, value: str | None) -> str | None: ...

    @abstractmethod
    def catalogue(self, locale: str = "default") -> Catalogue: ...

    @abstractmethod
    def for_send(self, ref) -> tuple[str, str] | None: ...

    @abstractmethod
    def message_emojis(self, content: str, cat: Catalogue | None = None) -> tuple[str, list[dict]]: ...
