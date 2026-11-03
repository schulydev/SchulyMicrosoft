from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.abstractions.i_teams_files import ITeamsFiles
from src.domain.validation.graph_ids import GraphIds


@dataclass
class ListDriveItemChildrenQuery(IQuery[list[dict]]):
    refresh_token: str = field(repr=False)
    drive_id: str
    item_id: str
    top: int


class ListDriveItemChildrenHandler(IQueryHandler[ListDriveItemChildrenQuery, list[dict]]):
    def __init__(self, accounts: IAccountRunner, files: ITeamsFiles):
        self._accounts = accounts
        self._files = files

    async def handle(self, query: ListDriveItemChildrenQuery) -> list[dict]:
        GraphIds.check(query.drive_id, GraphIds.DRIVE_ID_PATTERN, "drive_id")
        GraphIds.check(query.item_id, GraphIds.DRIVE_ITEM_PATTERN, "item_id")
        return await self._accounts.run(query.refresh_token, lambda note, broker: self._files.children(note, query.drive_id, query.item_id, query.top))
