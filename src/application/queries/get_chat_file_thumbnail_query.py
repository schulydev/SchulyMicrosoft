from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_file_thumbnails import IFileThumbnails
from src.application.services.account_image_reader import AccountImageReader
from src.application.services.chat_file_lookup import ChatFileLookup
from src.domain.files.binary_content import BinaryContent
from src.domain.validation.graph_ids import GraphIds


@dataclass
class GetChatFileThumbnailQuery(IQuery[BinaryContent]):
    refresh_token: str = field(repr=False)
    chat_id: str
    message_id: str
    attachment_id: str
    size: str


class GetChatFileThumbnailHandler(IQueryHandler[GetChatFileThumbnailQuery, BinaryContent]):
    def __init__(self, images: AccountImageReader, lookup: ChatFileLookup, thumbnails: IFileThumbnails):
        self._images = images
        self._lookup = lookup
        self._thumbnails = thumbnails

    async def handle(self, query: GetChatFileThumbnailQuery) -> BinaryContent:
        GraphIds.check(query.chat_id, GraphIds.CHAT_ID_PATTERN, "chat_id")
        GraphIds.check(query.message_id, GraphIds.MESSAGE_ID_PATTERN, "message_id")
        GraphIds.check(query.attachment_id, GraphIds.ATTACHMENT_ID_PATTERN, "attachment_id")
        self._images.check_thumbnail_size(query.size)

        def fetch(note, broker):
            ref = self._lookup.find(note, query.chat_id, query.message_id, query.attachment_id)
            if ref is None or not self._thumbnails.is_share_url(ref["contentUrl"]):
                return None
            return self._thumbnails.chat_file_thumbnail(note, broker, ref["contentUrl"], query.size)

        return await self._images.thumbnail(query.refresh_token, fetch)
