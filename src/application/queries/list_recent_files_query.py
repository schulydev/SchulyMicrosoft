from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.abstractions.i_teams_files import ITeamsFiles


@dataclass
class ListRecentFilesQuery(IQuery[list[dict]]):
    refresh_token: str = field(repr=False)
    top: int


class ListRecentFilesHandler(IQueryHandler[ListRecentFilesQuery, list[dict]]):
    def __init__(self, accounts: IAccountRunner, files: ITeamsFiles):
        self._accounts = accounts
        self._files = files

    async def handle(self, query: ListRecentFilesQuery) -> list[dict]:
        return await self._accounts.run(query.refresh_token, lambda note, broker: self._files.recent(note, query.top))
