from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.abstractions.i_graph_search import IGraphSearch
from src.domain.validation.graph_ids import GraphIds


@dataclass
class SearchQuery(IQuery[dict]):
    """`q` stays out of the repr: the query never reaches a log."""

    refresh_token: str = field(repr=False)
    q: str = field(repr=False)
    types: list[str]
    start: int
    size: int
    team_id: str | None


class SearchHandler(IQueryHandler[SearchQuery, dict]):
    def __init__(self, accounts: IAccountRunner, search: IGraphSearch):
        self._accounts = accounts
        self._search = search

    async def handle(self, query: SearchQuery) -> dict:
        if query.team_id is not None:
            GraphIds.check(query.team_id, GraphIds.TEAM_ID_PATTERN, "teamId")
        return await self._accounts.run(query.refresh_token, lambda note, broker: self._search.run(note, broker, query.q, query.types, query.start, query.size, query.team_id))
