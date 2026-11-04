from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.abstractions.i_chat_presence import IChatPresence
from src.domain.validation.graph_ids import GraphIds


@dataclass
class GetChatPresenceQuery(IQuery[dict]):
    refresh_token: str = field(repr=False)
    chat_id: str


class GetChatPresenceHandler(IQueryHandler[GetChatPresenceQuery, dict]):
    def __init__(self, accounts: IAccountRunner, presence: IChatPresence):
        self._accounts = accounts
        self._presence = presence

    async def handle(self, query: GetChatPresenceQuery) -> dict:
        GraphIds.check(query.chat_id, GraphIds.CHAT_ID_PATTERN, "chat_id")
        return await self._accounts.run(query.refresh_token, lambda note, broker: self._presence.of_chat(note, broker, query.chat_id))
