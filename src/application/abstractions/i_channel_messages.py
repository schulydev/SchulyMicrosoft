from abc import ABC, abstractmethod

from src.application.abstractions.i_graph_client import IGraphClient


class IChannelMessages(ABC):
    """Teams channel posts and replies, normalized."""

    @abstractmethod
    def messages(self, note: IGraphClient, team_id: str, channel_id: str, top: int) -> list[dict]: ...

    @abstractmethod
    def replies(self, note: IGraphClient, team_id: str, channel_id: str, message_id: str, top: int) -> list[dict]: ...
