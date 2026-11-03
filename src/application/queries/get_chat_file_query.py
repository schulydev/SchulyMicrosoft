from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.abstractions.i_microsoft_http_clients import IMicrosoftHttpClients
from src.application.abstractions.i_teams_files import ITeamsFiles
from src.application.services.chat_file_lookup import ChatFileLookup
from src.application.services.content_names import ContentNames
from src.application.services.drive_item_checks import DriveItemChecks
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


class GetChatFileHandler(IQueryHandler[GetChatFileQuery, FileStream]):
    def __init__(self, accounts: IAccountRunner, lookup: ChatFileLookup, files: ITeamsFiles, http: IMicrosoftHttpClients):
        self._accounts = accounts
        self._lookup = lookup
        self._files = files
        self._http = http

    async def handle(self, query: GetChatFileQuery) -> FileStream:
        GraphIds.check(query.chat_id, GraphIds.CHAT_ID_PATTERN, "chat_id")
        GraphIds.check(query.message_id, GraphIds.MESSAGE_ID_PATTERN, "message_id")
        GraphIds.check(query.attachment_id, GraphIds.ATTACHMENT_ID_PATTERN, "attachment_id")

        def resolve(note, broker):
            ref = self._lookup.find(note, query.chat_id, query.message_id, query.attachment_id)
            if ref is None:
                raise ServiceError(404, "File not found in the message.")
            item = note.get(GraphPaths.drive_item_path(ref["contentUrl"], "name,size,file,folder,@microsoft.graph.downloadUrl"))
            if item.get("folder") is not None:
                raise ServiceError(404, DriveItemChecks.FOLDER_DETAIL)
            if (item.get("size") or 0) > FileLimits.MAX_CHAT_FILE_BYTES:
                raise ServiceError(413, "The file is larger than 100 MB.")
            url = self._files.download_link(note, f"shares/{GraphPaths.share_id(ref['contentUrl'])}/driveItem", item)
            if not self._files.is_download_url(url):
                raise ServiceError(502, "The file has an unexpected download location.")
            return item, url

        item, url = await self._accounts.run(query.refresh_token, resolve)
        # The download URL is pre-authorized and short-lived; the bytes stream through without being held.
        return FileStream(self._http.stream_download(url, FileLimits.MAX_CHAT_FILE_BYTES, follow_redirects=False), ContentNames.safe_content_type((item.get("file") or {}).get("mimeType")), ContentNames.safe_name(item.get("name")))
