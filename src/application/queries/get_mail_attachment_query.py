from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.services.content_names import ContentNames
from src.application.services.mail_attachment_reader import MailAttachmentReader
from src.domain.files.binary_content import BinaryContent
from src.domain.validation.graph_ids import GraphIds


@dataclass
class GetMailAttachmentQuery(IQuery[BinaryContent]):
    refresh_token: str = field(repr=False)
    message_id: str
    attachment_id: str


class GetMailAttachmentHandler(IQueryHandler[GetMailAttachmentQuery, BinaryContent]):
    def __init__(self, accounts: IAccountRunner, attachments: MailAttachmentReader):
        self._accounts = accounts
        self._attachments = attachments

    async def handle(self, query: GetMailAttachmentQuery) -> BinaryContent:
        GraphIds.check(query.message_id, GraphIds.GRAPH_ID_PATTERN, "message_id")
        GraphIds.check(query.attachment_id, GraphIds.GRAPH_ID_PATTERN, "attachment_id")

        def fetch(note, broker):
            meta = self._attachments.metadata(note, query.message_id, query.attachment_id)
            self._attachments.check_declared_size(meta)
            return meta, self._attachments.download(note, query.message_id, query.attachment_id)

        meta, data = await self._accounts.run(query.refresh_token, fetch)
        name = ContentNames.safe_name(meta.get("name"))
        is_item = str(meta.get("@odata.type", "")).endswith("itemAttachment")
        content_type = ContentNames.safe_content_type("message/rfc822" if is_item else meta.get("contentType"))
        if is_item and "." not in name:
            name += ".eml"
        return BinaryContent(data, content_type, name)
