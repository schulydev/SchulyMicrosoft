from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.abstractions.i_teams_files import ITeamsFiles


@dataclass
class ListJoinedTeamsQuery(IQuery[list[dict]]):
    refresh_token: str = field(repr=False)


class ListJoinedTeamsHandler(IQueryHandler[ListJoinedTeamsQuery, list[dict]]):
    def __init__(self, accounts: IAccountRunner, files: ITeamsFiles):
        self._accounts = accounts
        self._files = files

    async def handle(self, query: ListJoinedTeamsQuery) -> list[dict]:
        return await self._accounts.run(query.refresh_token, self._files.joined_teams)
