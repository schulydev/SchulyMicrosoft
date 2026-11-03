from src.application.abstractions.i_pdf_converter import IPdfConverter
from src.domain.errors.service_error import ServiceError
from src.domain.files.file_limits import FileLimits


class DriveItemChecks:
    """What a drive item must be before it is read or converted."""

    FOLDER_DETAIL = "That item is a folder, which has no content to download."

    def __init__(self, pdf: IPdfConverter):
        self._pdf = pdf

    def check_file(self, item: dict) -> None:
        if isinstance(item, dict) and item.get("folder") is not None:
            raise ServiceError(404, self.FOLDER_DETAIL)
        if not isinstance(item, dict) or item.get("file") is None:
            raise ServiceError(404, "File not found.")

    def check_source(self, item: dict) -> None:
        if not isinstance(item, dict) or item.get("file") is None:
            raise ServiceError(404, "File not found.")
        if not self._pdf.is_convertible(item.get("name")):
            raise ServiceError(415, "This file type cannot be converted to PDF.")
        if (item.get("size") or 0) > FileLimits.MAX_CHAT_FILE_BYTES:
            raise ServiceError(413, "The file is larger than 100 MB.")
