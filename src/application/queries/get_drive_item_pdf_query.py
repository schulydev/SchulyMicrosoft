from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.abstractions.i_pdf_converter import IPdfConverter
from src.application.services.drive_item_checks import DriveItemChecks
from src.domain.files.spooled_pdf import SpooledPdf
from src.domain.validation.graph_ids import GraphIds


@dataclass
class GetDriveItemPdfQuery(IQuery[SpooledPdf]):
    refresh_token: str = field(repr=False)
    item_id: str


class GetDriveItemPdfHandler(IQueryHandler[GetDriveItemPdfQuery, SpooledPdf]):
    def __init__(self, accounts: IAccountRunner, pdf: IPdfConverter, checks: DriveItemChecks):
        self._accounts = accounts
        self._pdf = pdf
        self._checks = checks

    async def handle(self, query: GetDriveItemPdfQuery) -> SpooledPdf:
        GraphIds.check(query.item_id, GraphIds.DRIVE_ITEM_PATTERN, "item_id")

        def convert(note, broker):
            item = note.get(f"me/drive/items/{GraphIds.seg(query.item_id)}", {"$select": "id,name,size,file"})
            self._checks.check_source(item)
            return SpooledPdf(item.get("name"), self._pdf.drive_item_pdf(note, query.item_id))

        return await self._accounts.run(query.refresh_token, convert)
