from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.services.drive_file_text_reader import DriveFileTextReader
from src.domain.validation.graph_ids import GraphIds


@dataclass
class GetDriveItemTextQuery(IQuery[dict]):
    refresh_token: str = field(repr=False)
    item_id: str
    offset: int
    max_chars: int
    sheet: str | None
    row_offset: int
    max_rows: int


class GetDriveItemTextHandler(IQueryHandler[GetDriveItemTextQuery, dict]):
    def __init__(self, accounts: IAccountRunner, reader: DriveFileTextReader):
        self._accounts = accounts
        self._reader = reader

    async def handle(self, query: GetDriveItemTextQuery) -> dict:
        GraphIds.check(query.item_id, GraphIds.DRIVE_ITEM_PATTERN, "item_id")
        return await self._accounts.run(query.refresh_token, lambda note, broker: self._reader.read(note, None, query.item_id, query.offset, query.max_chars, query.sheet, query.row_offset, query.max_rows))
