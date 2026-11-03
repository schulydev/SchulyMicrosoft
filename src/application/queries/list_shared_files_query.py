from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.abstractions.i_teams_files import ITeamsFiles


@dataclass
class ListSharedFilesQuery(IQuery[list[dict]]):
    refresh_token: str = field(repr=False)
    top: int


class ListSharedFilesHandler(IQueryHandler[ListSharedFilesQuery, list[dict]]):
    def __init__(self, accounts: IAccountRunner, files: ITeamsFiles):
        self._accounts = accounts
        self._files = files

    async def handle(self, query: ListSharedFilesQuery) -> list[dict]:
        return await self._accounts.run(query.refresh_token, lambda note, broker: self._files.shared_with_me(note, query.top))
