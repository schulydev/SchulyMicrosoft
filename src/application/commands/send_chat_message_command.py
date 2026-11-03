from dataclasses import dataclass, field

from mediatorx import ICommand, ICommandHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.abstractions.i_chat_message_body import IChatMessageBody
from src.application.abstractions.i_chat_reader import IChatReader
from src.application.abstractions.i_chat_sender import IChatSender
from src.domain.chat.outgoing_message import OutgoingMessage
from src.domain.errors.service_error import ServiceError
from src.domain.files.file_limits import FileLimits
from src.domain.validation.graph_ids import GraphIds
from src.domain.validation.refresh_token_format import RefreshTokenFormat


@dataclass
class SendChatMessageCommand(ICommand[dict]):
    refresh_token: str = field(repr=False)
    chat_id: str
    body: IChatMessageBody


class SendChatMessageHandler(ICommandHandler[SendChatMessageCommand, dict]):
    def _outgoing(self, fields: dict, images: list, files: list) -> OutgoingMessage:
        content = fields.get("content")
        if content is None:
            content = fields.get("text")
        mentions = fields.get("mentions") or []
        gif = fields.get("gif")
        if not isinstance(content, (str, type(None))) or not isinstance(mentions, list) or not isinstance(gif, (dict, type(None))):
            raise ServiceError(400, "Invalid message fields.")
        content_type, importance = fields.get("contentType") or "text", fields.get("importance") or None
        if not isinstance(content_type, str) or not isinstance(importance, (str, type(None))):
            raise ServiceError(400, "Invalid message fields.")
        msg = OutgoingMessage(content=content or "", content_type=content_type, importance=importance, mentions=mentions, gif=gif, images=images, files=files)
        return self._sender.validate(msg)

    def __init__(self, accounts: IAccountRunner, sender: IChatSender, reader: IChatReader):
        self._accounts = accounts
        self._sender = sender
        self._reader = reader

    async def handle(self, command: SendChatMessageCommand) -> dict:
        GraphIds.check(command.chat_id, GraphIds.CHAT_ID_PATTERN, "chat_id")
        RefreshTokenFormat.check(command.refresh_token)
        body = command.body
        cap = FileLimits.MAX_SEND_BYTES if body.is_multipart else FileLimits.MAX_JSON_SEND_BYTES
        declared = body.declared_length
        if declared is not None and (not declared.isdigit() or int(declared) > cap):
            raise ServiceError(413, "The message is larger than the send limit.")
        try:
            fields, images, files = await body.read(cap)
            msg = self._outgoing(fields, images, files)

            def send(note, broker):
                created = self._sender.send(note, broker, command.chat_id, msg)
                return self._reader.enrich(note, broker, [created or {}])[0]

            return await self._accounts.run(command.refresh_token, send)
        finally:
            await body.close()
