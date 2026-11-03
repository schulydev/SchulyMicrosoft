from abc import ABC, abstractmethod

from src.application.abstractions.i_account_broker import IAccountBroker


class ITeamsChat(ABC):
    """The Teams chat service: group chat pictures and custom emoji."""

    @abstractmethod
    def mark_images(self, broker: IAccountBroker, chats: list[dict]) -> list[dict]: ...

    @abstractmethod
    def picture(self, broker: IAccountBroker, chat_id: str) -> bytes | None: ...

    @abstractmethod
    def custom_emoji(self, broker: IAccountBroker, document_id: str, animated: bool) -> bytes | None: ...
