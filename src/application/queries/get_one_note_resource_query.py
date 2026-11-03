from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_one_note import IOneNote
from src.application.abstractions.i_one_note_runner import IOneNoteRunner
from src.application.services.content_names import ContentNames
from src.application.services.image_sniffer import ImageSniffer
from src.domain.errors.resource_too_large import ResourceTooLarge
from src.domain.errors.service_error import ServiceError
from src.domain.files.binary_content import BinaryContent
from src.domain.files.file_limits import FileLimits
from src.domain.validation.graph_ids import GraphIds


@dataclass
class GetOneNoteResourceQuery(IQuery[BinaryContent]):
    refresh_token: str = field(repr=False)
    resource_id: str
    kind: str
    name: str | None


class GetOneNoteResourceHandler(IQueryHandler[GetOneNoteResourceQuery, BinaryContent]):
    def __init__(self, runner: IOneNoteRunner, onenote: IOneNote):
        self._runner = runner
        self._onenote = onenote

    async def handle(self, query: GetOneNoteResourceQuery) -> BinaryContent:
        GraphIds.check(query.resource_id, self._onenote.ID_PATTERN, "resource_id")
        if not self._onenote.is_id(query.resource_id):
            raise ServiceError(400, "Invalid resource_id.")
        if query.kind not in ("image", "file"):
            raise ServiceError(400, "kind must be image or file")

        def fetch(note, broker):
            try:
                return self._onenote.resource(broker, query.resource_id, FileLimits.MAX_DOWNLOAD_BYTES)
            except ResourceTooLarge:
                raise ServiceError(413, "The resource is larger than 25 MB.")

        data = await self._runner.run(query.refresh_token, fetch)
        if query.kind == "image":
            mime = ImageSniffer.chat_image((data or b"")[:12])
            if mime is None:
                raise ServiceError(415, "The resource is not a PNG, JPEG, GIF or WEBP image.")
            return BinaryContent(data, mime)
        return BinaryContent(data, "application/octet-stream", ContentNames.safe_name(query.name))
