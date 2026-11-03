from fastapi import APIRouter, Depends, Header, Query, Response
from fastapi.responses import StreamingResponse
from mediatorx import Mediator

from src.api.controller import controller
from src.api.dependencies import get_mediator
from src.api.http_headers import HttpHeaders
from src.api.responses.file_responses import FileResponses
from src.application.commands.create_mail_draft_command import CreateMailDraftCommand
from src.application.commands.delete_mail_command import DeleteMailCommand
from src.application.commands.flag_mail_command import FlagMailCommand
from src.application.commands.forward_mail_command import ForwardMailCommand
from src.application.commands.mark_mail_read_command import MarkMailReadCommand
from src.application.commands.move_mail_command import MoveMailCommand
from src.application.commands.reply_mail_command import ReplyMailCommand
from src.application.commands.send_mail_command import SendMailCommand
from src.application.commands.send_mail_draft_command import SendMailDraftCommand
from src.application.dtos.mail_flag_request import MailFlagRequest
from src.application.dtos.mail_forward_request import MailForwardRequest
from src.application.dtos.mail_message_in import MailMessageIn
from src.application.dtos.mail_move_request import MailMoveRequest
from src.application.dtos.mail_read_request import MailReadRequest
from src.application.dtos.mail_reply_request import MailReplyRequest
from src.application.queries.get_mail_attachment_pdf_query import GetMailAttachmentPdfQuery
from src.application.queries.get_mail_attachment_query import GetMailAttachmentQuery
from src.application.queries.get_mail_message_query import GetMailMessageQuery
from src.application.queries.list_mail_attachments_query import ListMailAttachmentsQuery
from src.application.queries.list_mail_folders_query import ListMailFoldersQuery
from src.application.queries.list_mail_query import ListMailQuery

router = APIRouter(prefix="/api")


@controller(router)
class MailController:
    mediator: Mediator = Depends(get_mediator)

    @router.get("/mail", tags=["Microsoft 365"])
    async def mail(self, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER), folder: str = Query("inbox"), top: int = Query(25, ge=1, le=500), skip: int = Query(0, ge=0, le=10000), unread: bool = Query(False), search: str | None = Query(None)):
        return await self.mediator.send(ListMailQuery(token, folder, top, skip, unread, search))

    # Fixed paths (folders/send/drafts) are declared before the {message_id} routes so they can never be read as an id.
    @router.get("/mail/folders", tags=["Microsoft 365"])
    async def mail_folders(self, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        return await self.mediator.send(ListMailFoldersQuery(token))

    @router.post("/mail/send", status_code=204, tags=["Microsoft 365"])
    async def mail_send(self, body: MailMessageIn, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        await self.mediator.send(SendMailCommand(token, body))
        return Response(status_code=204)

    @router.post("/mail/drafts", status_code=201, tags=["Microsoft 365"])
    async def mail_create_draft(self, body: MailMessageIn, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        return await self.mediator.send(CreateMailDraftCommand(token, body))

    @router.post("/mail/drafts/{message_id}/send", status_code=204, tags=["Microsoft 365"])
    async def mail_send_draft(self, message_id: str, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        await self.mediator.send(SendMailDraftCommand(token, message_id))
        return Response(status_code=204)

    @router.get("/mail/{message_id}", tags=["Microsoft 365"])
    async def mail_message(self, message_id: str, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        return await self.mediator.send(GetMailMessageQuery(token, message_id))

    @router.get("/mail/{message_id}/attachments", tags=["Microsoft 365"])
    async def mail_attachments(self, message_id: str, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        return await self.mediator.send(ListMailAttachmentsQuery(token, message_id))

    @router.get("/mail/{message_id}/attachments/{attachment_id}", tags=["Microsoft 365"], response_class=Response, responses={200: {"content": {"application/octet-stream": {}}}})
    async def mail_attachment(self, message_id: str, attachment_id: str, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        return FileResponses.attachment(await self.mediator.send(GetMailAttachmentQuery(token, message_id, attachment_id)))

    @router.get("/mail/{message_id}/attachments/{attachment_id}/pdf", tags=["Files as PDF"], response_class=StreamingResponse, responses={200: {"content": {"application/pdf": {}}}})
    async def mail_attachment_pdf(self, message_id: str, attachment_id: str, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        """A mail attachment (Word, Excel, PowerPoint, OpenDocument, RTF, CSV) converted to PDF through a temporary file in the app folder. 415 when the type can't be converted."""
        return FileResponses.pdf(await self.mediator.send(GetMailAttachmentPdfQuery(token, message_id, attachment_id)))

    @router.post("/mail/{message_id}/reply", status_code=204, tags=["Microsoft 365"])
    async def mail_reply(self, message_id: str, body: MailReplyRequest, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        await self.mediator.send(ReplyMailCommand(token, message_id, body.comment, body.replyAll))
        return Response(status_code=204)

    @router.post("/mail/{message_id}/forward", status_code=204, tags=["Microsoft 365"])
    async def mail_forward(self, message_id: str, body: MailForwardRequest, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        await self.mediator.send(ForwardMailCommand(token, message_id, body.to, body.comment))
        return Response(status_code=204)

    @router.post("/mail/{message_id}/read", tags=["Microsoft 365"])
    async def mail_mark_read(self, message_id: str, body: MailReadRequest, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        return await self.mediator.send(MarkMailReadCommand(token, message_id, body.read))

    @router.post("/mail/{message_id}/flag", tags=["Microsoft 365"])
    async def mail_flag(self, message_id: str, body: MailFlagRequest, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        return await self.mediator.send(FlagMailCommand(token, message_id, body.status))

    @router.post("/mail/{message_id}/move", tags=["Microsoft 365"])
    async def mail_move(self, message_id: str, body: MailMoveRequest, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        return await self.mediator.send(MoveMailCommand(token, message_id, body.folder))

    @router.delete("/mail/{message_id}", status_code=204, tags=["Microsoft 365"])
    async def mail_delete(self, message_id: str, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        await self.mediator.send(DeleteMailCommand(token, message_id))
        return Response(status_code=204)
