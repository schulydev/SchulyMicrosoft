import posixpath

from src.application.abstractions.i_file_text_extractor import IFileTextExtractor
from src.application.abstractions.i_graph_client import IGraphClient
from src.application.abstractions.i_pdf_converter import IPdfConverter
from src.application.abstractions.i_teams_files import ITeamsFiles
from src.application.services.drive_item_checks import DriveItemChecks
from src.domain.errors.service_error import ServiceError
from src.domain.files.file_text_limits import FileTextLimits


class DriveFileTextReader:
    """The FileText of a drive item: legacy formats go through a PDF conversion first."""

    def __init__(self, files: ITeamsFiles, pdf: IPdfConverter, text: IFileTextExtractor, checks: DriveItemChecks):
        self._files = files
        self._pdf = pdf
        self._text = text
        self._checks = checks

    def read(self, note: IGraphClient, drive_id: str | None, item_id: str, offset: int, max_chars: int, sheet: str | None, row_offset: int, max_rows: int) -> dict:
        item = note.get(self._files.item_base(drive_id, item_id), {"$select": "id,name,size,file,folder,@microsoft.graph.downloadUrl"})
        self._checks.check_file(item)
        name = item.get("name") or ""
        kind = self._text.kind_of(name)
        if kind is None:
            raise ServiceError(415, FileTextLimits.UNSUPPORTED)
        if (item.get("size") or 0) > self._text.MAX_SOURCE_BYTES and kind != "legacy":
            raise ServiceError(413, "The file is larger than 25 MB.")
        notes = []
        if kind == "legacy":
            spooled = self._pdf.drive_item_pdf(note, item_id, drive_id)
            try:
                data = spooled.read(self._text.MAX_SOURCE_BYTES + 1)
            finally:
                spooled.close()
            name = posixpath.splitext(name)[0] + ".pdf"
            notes.append("Converted to PDF by Microsoft 365 before reading.")
        else:
            url = self._files.download_link(note, self._files.item_base(drive_id, item_id), item)
            data = self._files.fetch_bytes(url, self._text.MAX_SOURCE_BYTES)
        result = self._text.extract(name, data, offset, max_chars, sheet, row_offset, max_rows, notes)
        result["name"] = item.get("name") or result["name"]
        return result
