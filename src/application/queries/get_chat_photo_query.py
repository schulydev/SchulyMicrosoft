from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_teams_chat import ITeamsChat
from src.application.services.account_image_reader import AccountImageReader
from src.domain.errors.chat_service_error import ChatServiceError
from src.domain.files.binary_content import BinaryContent
from src.domain.validation.graph_ids import GraphIds


@dataclass
class GetChatPhotoQuery(IQuery[BinaryContent]):
    refresh_token: str = field(repr=False)
    chat_id: str


class GetChatPhotoHandler(IQueryHandler[GetChatPhotoQuery, BinaryContent]):
    def __init__(self, images: AccountImageReader, teams_chat: ITeamsChat):
        self._images = images
        self._teams_chat = teams_chat

    async def handle(self, query: GetChatPhotoQuery) -> BinaryContent:
        GraphIds.check(query.chat_id, GraphIds.CHAT_ID_PATTERN, "chat_id")

        def fetch(note, broker):
            try:
                return self._teams_chat.picture(broker, query.chat_id)
            except ChatServiceError as ex:
                if ex.status in (401, 403):
                    # Teams refused this account (tenant policy, no Teams licence): there is no picture to show.
                    return None
                raise

        return await self._images.photo(query.refresh_token, fetch, "The chat has no picture.")
