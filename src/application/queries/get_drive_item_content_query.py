from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.abstractions.i_microsoft_http_clients import IMicrosoftHttpClients
from src.application.abstractions.i_teams_files import ITeamsFiles
from src.application.services.content_names import ContentNames
from src.application.services.drive_item_checks import DriveItemChecks
from src.domain.errors.service_error import ServiceError
from src.domain.files.file_stream import FileStream
from src.domain.validation.graph_ids import GraphIds


@dataclass
class GetDriveItemContentQuery(IQuery[FileStream]):
    refresh_token: str = field(repr=False)
    drive_id: str
    item_id: str


class GetDriveItemContentHandler(IQueryHandler[GetDriveItemContentQuery, FileStream]):
    def __init__(self, accounts: IAccountRunner, files: ITeamsFiles, checks: DriveItemChecks, http: IMicrosoftHttpClients):
        self._accounts = accounts
        self._files = files
        self._checks = checks
        self._http = http

    async def handle(self, query: GetDriveItemContentQuery) -> FileStream:
        GraphIds.check(query.drive_id, GraphIds.DRIVE_ID_PATTERN, "drive_id")
        GraphIds.check(query.item_id, GraphIds.DRIVE_ITEM_PATTERN, "item_id")

        def resolve(note, broker):
            item = note.get(self._files.item_base(query.drive_id, query.item_id), {"$select": "id,name,size,file,folder,@microsoft.graph.downloadUrl"})
            self._checks.check_file(item)
            if (item.get("size") or 0) > self._files.MAX_DOWNLOAD_BYTES:
                raise ServiceError(413, "The file is larger than 100 MB.")
            url = self._files.download_link(note, self._files.item_base(query.drive_id, query.item_id), item)
            if not self._files.is_download_url(url):
                raise ServiceError(502, "The file has an unexpected download location.")
            return item, url

        item, url = await self._accounts.run(query.refresh_token, resolve)
        return FileStream(self._http.stream_download(url, self._files.MAX_DOWNLOAD_BYTES, follow_redirects=False), ContentNames.safe_content_type((item.get("file") or {}).get("mimeType")), ContentNames.safe_name(item.get("name")))
