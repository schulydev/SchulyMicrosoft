from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import StreamingResponse
from mediatorx import Mediator

from src.api.controller import controller
from src.api.dependencies import get_mediator
from src.api.http_headers import HttpHeaders
from src.api.request_bodies.chat_message_request_body import ChatMessageRequestBody
from src.api.responses.file_responses import FileResponses
from src.application.commands.mark_chat_read_command import MarkChatReadCommand
from src.application.commands.schedule_chat_meeting_command import ScheduleChatMeetingCommand
from src.application.commands.send_chat_message_command import SendChatMessageCommand
from src.application.dtos.meeting_request import MeetingRequest
from src.application.queries.get_chat_file_pdf_query import GetChatFilePdfQuery
from src.application.queries.get_chat_file_query import GetChatFileQuery
from src.application.queries.get_chat_file_thumbnail_query import GetChatFileThumbnailQuery
from src.application.queries.get_chat_hosted_content_query import GetChatHostedContentQuery
from src.application.queries.get_chat_photo_query import GetChatPhotoQuery
from src.application.queries.get_chat_presence_query import GetChatPresenceQuery
from src.application.queries.list_chat_messages_query import ListChatMessagesQuery
from src.application.queries.list_chats_query import ListChatsQuery

router = APIRouter(prefix="/api")


@controller(router)
class ChatsController:
    mediator: Mediator = Depends(get_mediator)

    @router.get("/chats", tags=["Microsoft 365"])
    async def chats(self, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER), top: int = Query(25, le=200)):
        return await self.mediator.send(ListChatsQuery(token, top))

    @router.get("/chats/{chat_id}/messages", tags=["Microsoft 365"])
    async def chat_messages(self, chat_id: str, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER), top: int = Query(30, ge=1, le=300)):
        return await self.mediator.send(ListChatMessagesQuery(token, chat_id, top))

    @router.get("/chats/{chat_id}/messages/{message_id}/hostedContents/{hosted_id:path}", tags=["Microsoft 365"], response_class=Response, responses={200: {"content": {"image/png": {}}}})
    async def chat_hosted_content(self, chat_id: str, message_id: str, hosted_id: str, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        return FileResponses.image(await self.mediator.send(GetChatHostedContentQuery(token, chat_id, message_id, hosted_id)))

    @router.get("/chats/{chat_id}/messages/{message_id}/files/{attachment_id}", tags=["Microsoft 365"], response_class=StreamingResponse, responses={200: {"content": {"application/octet-stream": {}}}})
    async def chat_file(self, chat_id: str, message_id: str, attachment_id: str, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER), byte_range: str | None = Header(None, alias="Range")):
        return FileResponses.stream(await self.mediator.send(GetChatFileQuery(token, chat_id, message_id, attachment_id, byte_range)))

    @router.get("/chats/{chat_id}/messages/{message_id}/files/{attachment_id}/thumbnail", tags=["Microsoft 365"], response_class=Response, responses={200: {"content": {"image/jpeg": {}}}})
    async def chat_file_thumbnail(self, chat_id: str, message_id: str, attachment_id: str, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER), size: str = Query("medium")):
        """The preview image of a file shared in a message (`files[].hasThumbnail`): JPEG, PNG or WEBP; 404 when the file has none. size is small, medium or large."""
        return FileResponses.image(await self.mediator.send(GetChatFileThumbnailQuery(token, chat_id, message_id, attachment_id, size)))

    @router.get("/chats/{chat_id}/messages/{message_id}/files/{attachment_id}/pdf", tags=["Files as PDF"], response_class=StreamingResponse, responses={200: {"content": {"application/pdf": {}}}})
    async def chat_file_pdf(self, chat_id: str, message_id: str, attachment_id: str, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        """A file shared in a chat message (`files[].id`) converted to PDF where it lives (SharePoint / OneDrive). 415 when the type can't be converted."""
        return FileResponses.pdf(await self.mediator.send(GetChatFilePdfQuery(token, chat_id, message_id, attachment_id)))

    @router.post("/chats/{chat_id}/messages", tags=["Microsoft 365"])
    async def send_chat_message(self, chat_id: str, request: Request, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        """JSON `{content, contentType, importance, mentions, gif}` (or the legacy `{text}`), or multipart/form-data with the same fields (mentions and gif as JSON strings) plus `images` and `files` parts."""
        return await self.mediator.send(SendChatMessageCommand(token, chat_id, ChatMessageRequestBody(request)))

    @router.post("/chats/{chat_id}/meeting", status_code=201, tags=["Microsoft 365"])
    async def schedule_chat_meeting(self, chat_id: str, body: MeetingRequest, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        """Creates a Teams meeting in the user's calendar with the chat's members as attendees."""
        return await self.mediator.send(ScheduleChatMeetingCommand(token, chat_id, body))

    @router.post("/chats/{chat_id}/read", status_code=204, tags=["Microsoft 365"])
    async def mark_chat_read(self, chat_id: str, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        await self.mediator.send(MarkChatReadCommand(token, chat_id))
        return Response(status_code=204)

    @router.get("/chats/{chat_id}/presence", tags=["Microsoft 365"])
    async def chat_presence(self, chat_id: str, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        """The Teams status of the other person in a 1:1 chat: `{availability, activity}`, both null when there is none to show."""
        return await self.mediator.send(GetChatPresenceQuery(token, chat_id))

    @router.get("/chats/{chat_id}/photo", tags=["Microsoft 365"], response_class=Response, responses={200: {"content": {"image/jpeg": {}}}})
    async def chat_photo(self, chat_id: str, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        return FileResponses.image(await self.mediator.send(GetChatPhotoQuery(token, chat_id)))
