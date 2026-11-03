from dataclasses import dataclass, field

from mediatorx import ICommand, ICommandHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.abstractions.i_pdf_converter import IPdfConverter
from src.application.abstractions.i_request_body import IRequestBody
from src.application.services.content_names import ContentNames
from src.domain.errors.service_error import ServiceError
from src.domain.files.file_limits import FileLimits
from src.domain.files.spooled_pdf import SpooledPdf
from src.domain.validation.refresh_token_format import RefreshTokenFormat


@dataclass
class ConvertToPdfCommand(ICommand[SpooledPdf]):
    refresh_token: str = field(repr=False)
    name: str
    body: IRequestBody


class ConvertToPdfHandler(ICommandHandler[ConvertToPdfCommand, SpooledPdf]):
    def __init__(self, accounts: IAccountRunner, pdf: IPdfConverter):
        self._accounts = accounts
        self._pdf = pdf

    async def handle(self, command: ConvertToPdfCommand) -> SpooledPdf:
        RefreshTokenFormat.check(command.refresh_token)
        safe = ContentNames.safe_name(command.name)
        if not self._pdf.is_convertible(safe):
            raise ServiceError(415, "This file type cannot be converted to PDF.")
        declared = command.body.declared_length
        if declared is not None and (not declared.isdigit() or int(declared) > FileLimits.MAX_SEND_BYTES):
            raise ServiceError(413, "The file is larger than the conversion limit.")
        data = await command.body.read(FileLimits.MAX_SEND_BYTES)
        if not data:
            raise ServiceError(400, "The body is empty.")
        return await self._accounts.run(command.refresh_token, lambda note, broker: SpooledPdf(safe, self._pdf.bytes_pdf(note, broker, data, safe)))
