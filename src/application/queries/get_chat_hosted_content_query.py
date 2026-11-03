from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.services.graph_paths import GraphPaths
from src.application.services.image_sniffer import ImageSniffer
from src.domain.errors.service_error import ServiceError
from src.domain.files.binary_content import BinaryContent
from src.domain.files.file_limits import FileLimits
from src.domain.validation.graph_ids import GraphIds


@dataclass
class GetChatHostedContentQuery(IQuery[BinaryContent]):
    refresh_token: str = field(repr=False)
    chat_id: str
    message_id: str
    hosted_id: str


class GetChatHostedContentHandler(IQueryHandler[GetChatHostedContentQuery, BinaryContent]):
    def __init__(self, accounts: IAccountRunner):
        self._accounts = accounts

    async def handle(self, query: GetChatHostedContentQuery) -> BinaryContent:
        GraphIds.check(query.chat_id, GraphIds.CHAT_ID_PATTERN, "chat_id")
        GraphIds.check(query.message_id, GraphIds.MESSAGE_ID_PATTERN, "message_id")
        GraphIds.check(query.hosted_id, GraphIds.GRAPH_ID_PATTERN, "hosted_id")
        data = await self._accounts.run(query.refresh_token, lambda note, broker: note.get(f"{GraphPaths.message_path(query.chat_id, query.message_id)}/hostedContents/{GraphIds.seg(query.hosted_id)}/$value", raw="bytes"))
        mime = ImageSniffer.chat_image((data or b"")[:12])
        if mime is None:
            # Only images are proxied; anything else a hosted content could hold is refused.
            raise ServiceError(415, "The hosted content is not a PNG, JPEG, GIF or WEBP image.")
        if len(data) > FileLimits.MAX_DOWNLOAD_BYTES:
            raise ServiceError(413, "The image is larger than 25 MB.")
        return BinaryContent(data, mime)
