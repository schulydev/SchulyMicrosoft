from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.domain.validation.graph_ids import GraphIds


@dataclass
class GetMailMessageQuery(IQuery[dict]):
    refresh_token: str = field(repr=False)
    message_id: str


class GetMailMessageHandler(IQueryHandler[GetMailMessageQuery, dict]):
    def __init__(self, accounts: IAccountRunner):
        self._accounts = accounts

    async def handle(self, query: GetMailMessageQuery) -> dict:
        GraphIds.check(query.message_id, GraphIds.GRAPH_ID_PATTERN, "message_id")
        return await self._accounts.run(query.refresh_token, lambda note, broker: note.email(GraphIds.seg(query.message_id)))
