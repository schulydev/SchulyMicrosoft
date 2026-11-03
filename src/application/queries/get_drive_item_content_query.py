from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_teams_files import ITeamsFiles
from src.application.services.drive_item_checks import DriveItemChecks
from src.application.services.file_downloads import FileDownloads
from src.domain.errors.service_error import ServiceError
from src.domain.files.file_stream import FileStream
from src.domain.validation.graph_ids import GraphIds


@dataclass
class GetDriveItemContentQuery(IQuery[FileStream]):
    refresh_token: str = field(repr=False)
    drive_id: str
    item_id: str
    byte_range: str | None = None


class GetDriveItemContentHandler(IQueryHandler[GetDriveItemContentQuery, FileStream]):
    def __init__(self, files: ITeamsFiles, checks: DriveItemChecks, downloads: FileDownloads):
        self._files = files
        self._checks = checks
        self._downloads = downloads

    async def handle(self, query: GetDriveItemContentQuery) -> FileStream:
        GraphIds.check(query.drive_id, GraphIds.DRIVE_ID_PATTERN, "drive_id")
        GraphIds.check(query.item_id, GraphIds.DRIVE_ITEM_PATTERN, "item_id")

        def read(note, broker):
            item = note.get(self._files.item_base(query.drive_id, query.item_id), {"$select": "id,name,size,file,folder,@microsoft.graph.downloadUrl"})
            self._checks.check_file(item)
            if (item.get("size") or 0) > self._files.MAX_DOWNLOAD_BYTES:
                raise ServiceError(413, "The file is larger than 100 MB.")
            return item, self._files.download_link(note, self._files.item_base(query.drive_id, query.item_id), item)

        return await self._downloads.open(query.refresh_token, ("drive", query.drive_id, query.item_id), read, self._files.MAX_DOWNLOAD_BYTES, query.byte_range)
