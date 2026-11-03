from abc import ABC, abstractmethod

from src.application.abstractions.i_account_broker import IAccountBroker
from src.application.abstractions.i_graph_client import IGraphClient
from src.domain.chat.outgoing_message import OutgoingMessage


class IChatSender(ABC):
    """Validating and sending a chat message."""

    SELF_CHAT: str

    @abstractmethod
    def validate(self, msg: OutgoingMessage) -> OutgoingMessage: ...

    @abstractmethod
    def send(self, note: IGraphClient, broker: IAccountBroker, chat_id: str, msg: OutgoingMessage) -> dict: ...
