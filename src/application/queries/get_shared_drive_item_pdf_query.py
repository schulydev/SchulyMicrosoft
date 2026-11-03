from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.abstractions.i_pdf_converter import IPdfConverter
from src.application.abstractions.i_teams_files import ITeamsFiles
from src.application.services.drive_item_checks import DriveItemChecks
from src.domain.files.spooled_pdf import SpooledPdf
from src.domain.validation.graph_ids import GraphIds


@dataclass
class GetSharedDriveItemPdfQuery(IQuery[SpooledPdf]):
    refresh_token: str = field(repr=False)
    drive_id: str
    item_id: str


class GetSharedDriveItemPdfHandler(IQueryHandler[GetSharedDriveItemPdfQuery, SpooledPdf]):
    def __init__(self, accounts: IAccountRunner, files: ITeamsFiles, pdf: IPdfConverter, checks: DriveItemChecks):
        self._accounts = accounts
        self._files = files
        self._pdf = pdf
        self._checks = checks

    async def handle(self, query: GetSharedDriveItemPdfQuery) -> SpooledPdf:
        GraphIds.check(query.drive_id, GraphIds.DRIVE_ID_PATTERN, "drive_id")
        GraphIds.check(query.item_id, GraphIds.DRIVE_ITEM_PATTERN, "item_id")

        def convert(note, broker):
            item = note.get(self._files.item_base(query.drive_id, query.item_id), {"$select": "id,name,size,file"})
            self._checks.check_source(item)
            return SpooledPdf(item.get("name"), self._pdf.drive_item_pdf(note, query.item_id, query.drive_id))

        return await self._accounts.run(query.refresh_token, convert)
