from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.abstractions.i_channel_messages import IChannelMessages
from src.domain.validation.graph_ids import GraphIds


@dataclass
class ListChannelMessagesQuery(IQuery[list[dict]]):
    refresh_token: str = field(repr=False)
    team_id: str
    channel_id: str
    top: int


class ListChannelMessagesHandler(IQueryHandler[ListChannelMessagesQuery, list[dict]]):
    def __init__(self, accounts: IAccountRunner, channels: IChannelMessages):
        self._accounts = accounts
        self._channels = channels

    async def handle(self, query: ListChannelMessagesQuery) -> list[dict]:
        GraphIds.check(query.team_id, GraphIds.TEAM_ID_PATTERN, "team_id")
        GraphIds.check(query.channel_id, GraphIds.CHANNEL_ID_PATTERN, "channel_id")
        return await self._accounts.run(query.refresh_token, lambda note, broker: self._channels.messages(note, query.team_id, query.channel_id, query.top))
