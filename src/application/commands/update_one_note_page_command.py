from dataclasses import dataclass, field

from mediatorx import ICommand, ICommandHandler

from src.application.abstractions.i_one_note import IOneNote
from src.application.abstractions.i_one_note_runner import IOneNoteRunner
from src.application.dtos.one_note_page_update import OneNotePageUpdate
from src.application.services.mail_message_builder import MailMessageBuilder
from src.application.services.onenote_html_sanitizer import OneNoteHtmlSanitizer
from src.domain.errors.service_error import ServiceError
from src.domain.validation.graph_ids import GraphIds


@dataclass
class UpdateOneNotePageCommand(ICommand[dict]):
    refresh_token: str = field(repr=False)
    page_id: str
    body: OneNotePageUpdate


class UpdateOneNotePageHandler(ICommandHandler[UpdateOneNotePageCommand, dict]):
    def __init__(self, runner: IOneNoteRunner, onenote: IOneNote, builder: MailMessageBuilder, html: OneNoteHtmlSanitizer):
        self._runner = runner
        self._onenote = onenote
        self._builder = builder
        self._html = html

    async def handle(self, command: UpdateOneNotePageCommand) -> dict:
        GraphIds.check(command.page_id, self._onenote.ID_PATTERN, "page_id")
        if not self._onenote.is_id(command.page_id):
            raise ServiceError(400, "Invalid page_id.")
        body = command.body
        outlines = [{"id": o.id, "html": o.html} for o in body.outlines or []]
        for item in outlines:
            GraphIds.check(item["id"], self._html.SAFE_ID, "outline id")
        self._builder.check_text((body.append or "") + "".join(o["html"] for o in outlines), "html")
        return await self._runner.run(command.refresh_token, lambda note, broker: self._onenote.update_page(note, broker, command.page_id, body.title, outlines, body.append))
