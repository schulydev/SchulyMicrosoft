from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_chat_reader import IChatReader
from src.application.abstractions.i_file_thumbnails import IFileThumbnails
from src.application.abstractions.i_teams_files import ITeamsFiles
from src.application.services.drive_item_checks import DriveItemChecks
from src.application.services.file_downloads import FileDownloads
from src.application.services.graph_paths import GraphPaths
from src.domain.errors.service_error import ServiceError
from src.domain.files.file_limits import FileLimits
from src.domain.files.file_stream import FileStream
from src.domain.validation.graph_ids import GraphIds


@dataclass
class GetChatFileQuery(IQuery[FileStream]):
    refresh_token: str = field(repr=False)
    chat_id: str
    message_id: str
    attachment_id: str
    byte_range: str | None = None


class GetChatFileHandler(IQueryHandler[GetChatFileQuery, FileStream]):
    def __init__(self, reader: IChatReader, thumbnails: IFileThumbnails, files: ITeamsFiles, downloads: FileDownloads):
        self._reader = reader
        self._thumbnails = thumbnails
        self._files = files
        self._downloads = downloads

    async def handle(self, query: GetChatFileQuery) -> FileStream:
        GraphIds.check(query.chat_id, GraphIds.CHAT_ID_PATTERN, "chat_id")
        GraphIds.check(query.message_id, GraphIds.MESSAGE_ID_PATTERN, "message_id")
        GraphIds.check(query.attachment_id, GraphIds.ATTACHMENT_ID_PATTERN, "attachment_id")

        def read(note, broker):
            ref = self._reader.file_ref(note, broker, query.chat_id, query.message_id, query.attachment_id)
            if ref is None:
                raise ServiceError(404, "File not found in the message.")
            path = GraphPaths.share_item_path(ref["contentUrl"])
            # Throttled, this answers at once: the caller waits, rather than a worker thread.
            item = note.get(path, retry=False)
            if item.get("folder") is not None:
                raise ServiceError(404, DriveItemChecks.FOLDER_DETAIL)
            if (item.get("size") or 0) > FileLimits.MAX_CHAT_FILE_BYTES:
                raise ServiceError(413, "The file is larger than 100 MB.")
            self._thumbnails.remember_item(broker, ref["contentUrl"], item)
            return item, self._files.download_link(note, path, item)

        key = ("chat", query.chat_id, query.message_id, query.attachment_id)
        # The link is pre-authorized and short-lived; the bytes stream through without being held.
        return await self._downloads.open(query.refresh_token, key, read, FileLimits.MAX_CHAT_FILE_BYTES, query.byte_range)
