from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.abstractions.i_teams_files import ITeamsFiles
from src.domain.errors.service_error import ServiceError
from src.domain.validation.graph_ids import GraphIds


@dataclass
class ListTeamFilesQuery(IQuery[dict]):
    refresh_token: str = field(repr=False)
    team_id: str
    channel_id: str | None
    path: str | None
    top: int


class ListTeamFilesHandler(IQueryHandler[ListTeamFilesQuery, dict]):
    def __init__(self, accounts: IAccountRunner, files: ITeamsFiles):
        self._accounts = accounts
        self._files = files

    async def handle(self, query: ListTeamFilesQuery) -> dict:
        GraphIds.check(query.team_id, GraphIds.TEAM_ID_PATTERN, "team_id")
        if query.channel_id:
            GraphIds.check(query.channel_id, GraphIds.CHANNEL_ID_PATTERN, "channel_id")
        try:
            self._files.valid_path(query.path)
        except ValueError:
            raise ServiceError(400, "Invalid path.")
        return await self._accounts.run(query.refresh_token, lambda note, broker: self._files.team_files(note, broker, query.team_id, query.channel_id or None, query.path, query.top))
