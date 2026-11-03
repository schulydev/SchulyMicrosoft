import posixpath
from dataclasses import dataclass, field

from mediatorx import ICommand, ICommandHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.abstractions.i_file_text_extractor import IFileTextExtractor
from src.application.abstractions.i_pdf_converter import IPdfConverter
from src.application.abstractions.i_request_body import IRequestBody
from src.application.services.content_names import ContentNames
from src.domain.errors.service_error import ServiceError
from src.domain.files.file_limits import FileLimits
from src.domain.files.file_text_limits import FileTextLimits
from src.domain.validation.refresh_token_format import RefreshTokenFormat


@dataclass
class ConvertToTextCommand(ICommand[dict]):
    refresh_token: str = field(repr=False)
    name: str
    offset: int
    max_chars: int
    sheet: str | None
    row_offset: int
    max_rows: int
    body: IRequestBody


class ConvertToTextHandler(ICommandHandler[ConvertToTextCommand, dict]):
    def __init__(self, accounts: IAccountRunner, pdf: IPdfConverter, text: IFileTextExtractor):
        self._accounts = accounts
        self._pdf = pdf
        self._text = text

    async def handle(self, command: ConvertToTextCommand) -> dict:
        RefreshTokenFormat.check(command.refresh_token)
        safe = ContentNames.safe_name(command.name)
        if self._text.kind_of(safe) is None:
            raise ServiceError(415, FileTextLimits.UNSUPPORTED)
        declared = command.body.declared_length
        if declared is not None and (not declared.isdigit() or int(declared) > FileLimits.MAX_TEXT_SOURCE_BYTES):
            raise ServiceError(413, "The file is larger than 25 MB.")
        data = await command.body.read(FileLimits.MAX_TEXT_SOURCE_BYTES)
        if not data:
            raise ServiceError(400, "The body is empty.")

        def run(note, broker):
            notes = []
            if self._text.kind_of(safe) == "legacy":
                spooled = self._pdf.bytes_pdf(note, broker, data, safe)
                try:
                    pdf = spooled.read(self._text.MAX_SOURCE_BYTES + 1)
                finally:
                    spooled.close()
                notes.append("Converted to PDF by Microsoft 365 before reading.")
                result = self._text.extract(posixpath.splitext(safe)[0] + ".pdf", pdf, command.offset, command.max_chars, command.sheet, command.row_offset, command.max_rows, notes)
                result["name"] = safe
                return result
            return self._text.extract(safe, data, command.offset, command.max_chars, command.sheet, command.row_offset, command.max_rows, notes)

        return await self._accounts.run(command.refresh_token, run)
