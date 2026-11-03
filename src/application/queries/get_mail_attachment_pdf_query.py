from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.abstractions.i_pdf_converter import IPdfConverter
from src.application.services.mail_attachment_reader import MailAttachmentReader
from src.domain.errors.service_error import ServiceError
from src.domain.files.spooled_pdf import SpooledPdf
from src.domain.validation.graph_ids import GraphIds


@dataclass
class GetMailAttachmentPdfQuery(IQuery[SpooledPdf]):
    refresh_token: str = field(repr=False)
    message_id: str
    attachment_id: str


class GetMailAttachmentPdfHandler(IQueryHandler[GetMailAttachmentPdfQuery, SpooledPdf]):
    def __init__(self, accounts: IAccountRunner, attachments: MailAttachmentReader, pdf: IPdfConverter):
        self._accounts = accounts
        self._attachments = attachments
        self._pdf = pdf

    async def handle(self, query: GetMailAttachmentPdfQuery) -> SpooledPdf:
        GraphIds.check(query.message_id, GraphIds.GRAPH_ID_PATTERN, "message_id")
        GraphIds.check(query.attachment_id, GraphIds.GRAPH_ID_PATTERN, "attachment_id")

        def convert(note, broker):
            meta = self._attachments.metadata(note, query.message_id, query.attachment_id)
            if str(meta.get("@odata.type", "")).endswith("itemAttachment") or not self._pdf.is_convertible(meta.get("name")):
                raise ServiceError(415, "This file type cannot be converted to PDF.")
            self._attachments.check_declared_size(meta)
            data = self._attachments.download(note, query.message_id, query.attachment_id)
            return SpooledPdf(meta.get("name"), self._pdf.bytes_pdf(note, broker, data, meta.get("name")))

        return await self._accounts.run(query.refresh_token, convert)
