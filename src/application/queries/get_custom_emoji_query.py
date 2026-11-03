from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.abstractions.i_teams_chat import ITeamsChat
from src.application.services.image_sniffer import ImageSniffer
from src.domain.errors.chat_service_error import ChatServiceError
from src.domain.errors.service_error import ServiceError
from src.domain.files.binary_content import BinaryContent
from src.domain.validation.graph_ids import GraphIds


@dataclass
class GetCustomEmojiQuery(IQuery[BinaryContent]):
    refresh_token: str = field(repr=False)
    document_id: str
    animated: bool


class GetCustomEmojiHandler(IQueryHandler[GetCustomEmojiQuery, BinaryContent]):
    def __init__(self, accounts: IAccountRunner, teams_chat: ITeamsChat):
        self._accounts = accounts
        self._teams_chat = teams_chat

    async def handle(self, query: GetCustomEmojiQuery) -> BinaryContent:
        GraphIds.check(query.document_id, GraphIds.DOCUMENT_ID_PATTERN, "document_id")

        def fetch(note, broker):
            try:
                return self._teams_chat.custom_emoji(broker, query.document_id, query.animated)
            except ChatServiceError as ex:
                if ex.status in (401, 403):
                    return None
                raise

        data = await self._accounts.run(query.refresh_token, fetch)
        mime = ImageSniffer.chat_image((data or b"")[:12])
        if mime is None:
            raise ServiceError(404, "No such custom emoji.")
        return BinaryContent(data, mime)
