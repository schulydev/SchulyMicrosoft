from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.domain.errors.service_error import ServiceError
from src.domain.validation.graph_ids import GraphIds


@dataclass
class ListFilesQuery(IQuery[list[dict]]):
    refresh_token: str = field(repr=False)
    path: str
    top: int


class ListFilesHandler(IQueryHandler[ListFilesQuery, list[dict]]):
    def __init__(self, accounts: IAccountRunner):
        self._accounts = accounts

    async def handle(self, query: ListFilesQuery) -> list[dict]:
        if GraphIds.has_dot_segment(query.path) or "%" in query.path:
            raise ServiceError(400, "Invalid path.")
        return await self._accounts.run(query.refresh_token, lambda note, broker: note.files(path=query.path, top=query.top))
