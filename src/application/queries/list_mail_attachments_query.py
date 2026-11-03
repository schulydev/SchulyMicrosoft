from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.services.mail_attachment_reader import MailAttachmentReader
from src.domain.validation.graph_ids import GraphIds


@dataclass
class ListMailAttachmentsQuery(IQuery[list[dict]]):
    refresh_token: str = field(repr=False)
    message_id: str


class ListMailAttachmentsHandler(IQueryHandler[ListMailAttachmentsQuery, list[dict]]):
    def __init__(self, accounts: IAccountRunner, attachments: MailAttachmentReader):
        self._accounts = accounts
        self._attachments = attachments

    async def handle(self, query: ListMailAttachmentsQuery) -> list[dict]:
        GraphIds.check(query.message_id, GraphIds.GRAPH_ID_PATTERN, "message_id")
        return await self._accounts.run(query.refresh_token, lambda note, broker: [self._attachments.attachment_meta(a) for a in note.list(f"me/messages/{GraphIds.seg(query.message_id)}/attachments")])
