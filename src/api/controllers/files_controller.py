from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import StreamingResponse
from mediatorx import Mediator

from src.api.controller import controller
from src.api.dependencies import get_mediator
from src.api.http_headers import HttpHeaders
from src.api.request_bodies.raw_request_body import RawRequestBody
from src.api.responses.file_responses import FileResponses
from src.application.commands.convert_to_pdf_command import ConvertToPdfCommand
from src.application.commands.convert_to_text_command import ConvertToTextCommand
from src.application.queries.get_drive_item_content_query import GetDriveItemContentQuery
from src.application.queries.get_drive_item_pdf_query import GetDriveItemPdfQuery
from src.application.queries.get_drive_item_query import GetDriveItemQuery
from src.application.queries.get_drive_item_text_query import GetDriveItemTextQuery
from src.application.queries.get_drive_thumbnail_query import GetDriveThumbnailQuery
from src.application.queries.get_shared_drive_item_pdf_query import GetSharedDriveItemPdfQuery
from src.application.queries.get_shared_drive_item_text_query import GetSharedDriveItemTextQuery
from src.application.queries.get_shared_drive_thumbnail_query import GetSharedDriveThumbnailQuery
from src.application.queries.list_drive_item_children_query import ListDriveItemChildrenQuery
from src.application.queries.list_files_query import ListFilesQuery
from src.application.queries.list_recent_files_query import ListRecentFilesQuery
from src.application.queries.list_shared_files_query import ListSharedFilesQuery
from src.domain.files.file_text_limits import FileTextLimits

router = APIRouter(prefix="/api")


class FileTextParameters:
    """The paging parameters every FileText route shares."""

    OFFSET = Query(0, ge=0, le=100_000_000)
    CHARS = Query(FileTextLimits.DEFAULT_CHARS, ge=1, le=FileTextLimits.MAX_CHARS)
    SHEET = Query(None, max_length=64)
    ROW_OFFSET = Query(0, ge=0, le=FileTextLimits.MAX_ROW_OFFSET)
    ROWS = Query(FileTextLimits.DEFAULT_ROWS, ge=1, le=FileTextLimits.MAX_ROWS)


@controller(router)
class FilesController:
    mediator: Mediator = Depends(get_mediator)

    @router.get("/files", tags=["Microsoft 365"])
    async def files(self, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER), path: str = Query("root"), top: int = Query(100, le=1000)):
        return await self.mediator.send(ListFilesQuery(token, path, top))

    @router.get("/files/{item_id}/thumbnail", tags=["Microsoft 365"], response_class=Response, responses={200: {"content": {"image/jpeg": {}}}})
    async def drive_thumbnail(self, item_id: str, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER), size: str = Query("medium")):
        """The preview image of a OneDrive item (an `id` from /api/files); 404 when it has none."""
        return FileResponses.image(await self.mediator.send(GetDriveThumbnailQuery(token, item_id, size)))

    @router.get("/drives/{drive_id}/items/{item_id}/thumbnail", tags=["Teams files"], response_class=Response, responses={200: {"content": {"image/jpeg": {}}}})
    async def shared_drive_thumbnail(self, drive_id: str, item_id: str, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER), size: str = Query("medium")):
        """The preview image of an item in any drive the user can read (a team library, a shared drive); 404 when it has none."""
        return FileResponses.image(await self.mediator.send(GetSharedDriveThumbnailQuery(token, drive_id, item_id, size)))

    @router.get("/files/{item_id}/pdf", tags=["Files as PDF"], response_class=StreamingResponse, responses={200: {"content": {"application/pdf": {}}}})
    async def drive_item_pdf(self, item_id: str, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        """A OneDrive item (an `id` from /api/files) converted to PDF by Microsoft 365. 415 when the type can't be converted."""
        return FileResponses.pdf(await self.mediator.send(GetDriveItemPdfQuery(token, item_id)))

    @router.post("/convert/pdf", tags=["Files as PDF"], response_class=StreamingResponse, responses={200: {"content": {"application/pdf": {}}}})
    async def convert_pdf(self, request: Request, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER), name: str = Query(..., min_length=1, max_length=255)):
        """The request body (raw bytes, up to 105 MB) converted to PDF; `name` is the file name, whose extension picks the type (Word, Excel, PowerPoint, OpenDocument, RTF, CSV).

        For files that aren't in a drive: they go to a temporary file in the app folder, which is deleted right after the conversion."""
        return FileResponses.pdf(await self.mediator.send(ConvertToPdfCommand(token, name, RawRequestBody(request))))

    @router.get("/drives/{drive_id}/items/{item_id}", tags=["Teams files"])
    async def drive_item(self, drive_id: str, item_id: str, response: Response, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        """One driveItem with a fresh download URL."""
        response.headers["Cache-Control"] = "no-store"
        return await self.mediator.send(GetDriveItemQuery(token, drive_id, item_id))

    @router.get("/drives/{drive_id}/items/{item_id}/children", tags=["Teams files"])
    async def drive_item_children(self, drive_id: str, item_id: str, response: Response, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER), top: int = Query(100, ge=1, le=1000)):
        response.headers["Cache-Control"] = "no-store"
        return await self.mediator.send(ListDriveItemChildrenQuery(token, drive_id, item_id, top))

    @router.get("/drives/{drive_id}/items/{item_id}/content", tags=["Teams files"], response_class=StreamingResponse, responses={200: {"content": {"application/octet-stream": {}}}})
    async def drive_item_content(self, drive_id: str, item_id: str, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER), byte_range: str | None = Header(None, alias="Range")):
        """The file's bytes as an attachment (<= 100 MB, no-store)."""
        return FileResponses.stream(await self.mediator.send(GetDriveItemContentQuery(token, drive_id, item_id, byte_range)))

    @router.get("/drives/{drive_id}/items/{item_id}/pdf", tags=["Files as PDF"], response_class=StreamingResponse, responses={200: {"content": {"application/pdf": {}}}})
    async def shared_drive_item_pdf(self, drive_id: str, item_id: str, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        """An item of any readable drive converted to PDF by Microsoft 365. 415 when the type can't be converted."""
        return FileResponses.pdf(await self.mediator.send(GetSharedDriveItemPdfQuery(token, drive_id, item_id)))

    @router.get("/drives/{drive_id}/items/{item_id}/text", tags=["File text"])
    async def shared_drive_item_text(self, drive_id: str, item_id: str, response: Response, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER), offset: int = FileTextParameters.OFFSET, max_chars: int = FileTextParameters.CHARS, sheet: str | None = FileTextParameters.SHEET, row_offset: int = FileTextParameters.ROW_OFFSET, max_rows: int = FileTextParameters.ROWS):
        """Plain text of a document, spreadsheet, presentation, PDF or text file (FileText), paged by characters (and rows for a sheet)."""
        response.headers["Cache-Control"] = "no-store"
        return await self.mediator.send(GetSharedDriveItemTextQuery(token, drive_id, item_id, offset, max_chars, sheet, row_offset, max_rows))

    @router.get("/files/{item_id}/text", tags=["File text"])
    async def drive_item_text(self, item_id: str, response: Response, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER), offset: int = FileTextParameters.OFFSET, max_chars: int = FileTextParameters.CHARS, sheet: str | None = FileTextParameters.SHEET, row_offset: int = FileTextParameters.ROW_OFFSET, max_rows: int = FileTextParameters.ROWS):
        """FileText of an item in the user's own OneDrive."""
        response.headers["Cache-Control"] = "no-store"
        return await self.mediator.send(GetDriveItemTextQuery(token, item_id, offset, max_chars, sheet, row_offset, max_rows))

    @router.post("/convert/text", tags=["File text"])
    async def convert_text(self, request: Request, response: Response, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER), name: str = Query(..., min_length=1, max_length=255), offset: int = FileTextParameters.OFFSET, max_chars: int = FileTextParameters.CHARS, sheet: str | None = FileTextParameters.SHEET, row_offset: int = FileTextParameters.ROW_OFFSET, max_rows: int = FileTextParameters.ROWS):
        """FileText of the request body (raw bytes, up to 25 MB); `name`'s extension picks the type. For files that aren't in a drive."""
        response.headers["Cache-Control"] = "no-store"
        return await self.mediator.send(ConvertToTextCommand(token, name, offset, max_chars, sheet, row_offset, max_rows, RawRequestBody(request)))

    @router.get("/files/shared", tags=["Teams files"])
    async def files_shared(self, response: Response, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER), top: int = Query(50, ge=1, le=200)):
        """Files shared with the user, flattened from `remoteItem`, each with `parentReference.driveId` and `shared: {sharedBy, sharedDateTime}`."""
        response.headers["Cache-Control"] = "no-store"
        return await self.mediator.send(ListSharedFilesQuery(token, top))

    @router.get("/files/recent", tags=["Teams files"])
    async def files_recent(self, response: Response, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER), top: int = Query(50, ge=1, le=200)):
        response.headers["Cache-Control"] = "no-store"
        return await self.mediator.send(ListRecentFilesQuery(token, top))
