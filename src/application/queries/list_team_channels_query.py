from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.abstractions.i_teams_files import ITeamsFiles
from src.domain.validation.graph_ids import GraphIds


@dataclass
class ListTeamChannelsQuery(IQuery[list[dict]]):
    refresh_token: str = field(repr=False)
    team_id: str


class ListTeamChannelsHandler(IQueryHandler[ListTeamChannelsQuery, list[dict]]):
    def __init__(self, accounts: IAccountRunner, files: ITeamsFiles):
        self._accounts = accounts
        self._files = files

    async def handle(self, query: ListTeamChannelsQuery) -> list[dict]:
        GraphIds.check(query.team_id, GraphIds.TEAM_ID_PATTERN, "team_id")
        return await self._accounts.run(query.refresh_token, lambda note, broker: self._files.channels(note, broker, query.team_id))
