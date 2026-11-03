from dataclasses import dataclass, field

from mediatorx import ICommand, ICommandHandler

from src.application.abstractions.i_one_note import IOneNote
from src.application.abstractions.i_one_note_runner import IOneNoteRunner
from src.application.dtos.one_note_page_create import OneNotePageCreate
from src.application.services.mail_message_builder import MailMessageBuilder
from src.domain.errors.service_error import ServiceError
from src.domain.validation.graph_ids import GraphIds


@dataclass
class CreateOneNotePageCommand(ICommand[dict]):
    refresh_token: str = field(repr=False)
    section_id: str
    body: OneNotePageCreate


class CreateOneNotePageHandler(ICommandHandler[CreateOneNotePageCommand, dict]):
    def __init__(self, runner: IOneNoteRunner, onenote: IOneNote, builder: MailMessageBuilder):
        self._runner = runner
        self._onenote = onenote
        self._builder = builder

    async def handle(self, command: CreateOneNotePageCommand) -> dict:
        GraphIds.check(command.section_id, self._onenote.ID_PATTERN, "section_id")
        if not self._onenote.is_id(command.section_id):
            raise ServiceError(400, "Invalid section_id.")
        self._builder.check_text(command.body.html or "", "html")
        return await self._runner.run(command.refresh_token, lambda note, broker: self._onenote.create_page(note, broker, command.section_id, command.body.title, command.body.html))
