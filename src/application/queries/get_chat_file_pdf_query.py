from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.abstractions.i_chat_reader import IChatReader
from src.application.abstractions.i_file_thumbnails import IFileThumbnails
from src.application.abstractions.i_pdf_converter import IPdfConverter
from src.application.services.drive_item_checks import DriveItemChecks
from src.application.services.graph_paths import GraphPaths
from src.domain.errors.service_error import ServiceError
from src.domain.files.spooled_pdf import SpooledPdf
from src.domain.validation.graph_ids import GraphIds


@dataclass
class GetChatFilePdfQuery(IQuery[SpooledPdf]):
    refresh_token: str = field(repr=False)
    chat_id: str
    message_id: str
    attachment_id: str


class GetChatFilePdfHandler(IQueryHandler[GetChatFilePdfQuery, SpooledPdf]):
    def __init__(self, accounts: IAccountRunner, reader: IChatReader, thumbnails: IFileThumbnails, pdf: IPdfConverter, checks: DriveItemChecks):
        self._accounts = accounts
        self._reader = reader
        self._thumbnails = thumbnails
        self._pdf = pdf
        self._checks = checks

    async def handle(self, query: GetChatFilePdfQuery) -> SpooledPdf:
        GraphIds.check(query.chat_id, GraphIds.CHAT_ID_PATTERN, "chat_id")
        GraphIds.check(query.message_id, GraphIds.MESSAGE_ID_PATTERN, "message_id")
        GraphIds.check(query.attachment_id, GraphIds.ATTACHMENT_ID_PATTERN, "attachment_id")

        def convert(note, broker):
            ref = self._reader.file_ref(note, broker, query.chat_id, query.message_id, query.attachment_id)
            if ref is None:
                raise ServiceError(404, "File not found in the message.")
            if not self._thumbnails.is_share_url(ref.get("contentUrl")):
                raise ServiceError(415, "Only files in SharePoint or OneDrive can be converted.")
            item = note.get(GraphPaths.drive_item_path(ref["contentUrl"], "id,name,size,file,parentReference"))
            self._checks.check_source(item)
            drive_id = (item.get("parentReference") or {}).get("driveId")
            if not self._thumbnails.safe_graph_id(drive_id) or not self._thumbnails.safe_graph_id(item.get("id")):
                raise ServiceError(404, "File not found.")
            return SpooledPdf(item.get("name"), self._pdf.drive_item_pdf(note, item["id"], drive_id))

        return await self._accounts.run(query.refresh_token, convert)
