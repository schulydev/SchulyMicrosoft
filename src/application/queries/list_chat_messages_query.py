from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.abstractions.i_chat_reader import IChatReader
from src.domain.validation.graph_ids import GraphIds


@dataclass
class ListChatMessagesQuery(IQuery[list[dict]]):
    refresh_token: str = field(repr=False)
    chat_id: str
    top: int


class ListChatMessagesHandler(IQueryHandler[ListChatMessagesQuery, list[dict]]):
    def __init__(self, accounts: IAccountRunner, reader: IChatReader):
        self._accounts = accounts
        self._reader = reader

    async def handle(self, query: ListChatMessagesQuery) -> list[dict]:
        GraphIds.check(query.chat_id, GraphIds.CHAT_ID_PATTERN, "chat_id")
        # No $select: Graph answers 500 for chat messages when one is set.
        return await self._accounts.run(query.refresh_token, lambda note, broker: self._reader.enrich(note, broker, note.list(f"me/chats/{query.chat_id}/messages", {"$top": min(query.top, 50)}, limit=query.top)))
