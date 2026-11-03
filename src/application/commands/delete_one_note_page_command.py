from dataclasses import dataclass, field

from mediatorx import ICommand, ICommandHandler

from src.application.abstractions.i_one_note import IOneNote
from src.application.abstractions.i_one_note_runner import IOneNoteRunner
from src.domain.errors.service_error import ServiceError
from src.domain.validation.graph_ids import GraphIds


@dataclass
class DeleteOneNotePageCommand(ICommand[None]):
    refresh_token: str = field(repr=False)
    page_id: str


class DeleteOneNotePageHandler(ICommandHandler[DeleteOneNotePageCommand, None]):
    def __init__(self, runner: IOneNoteRunner, onenote: IOneNote):
        self._runner = runner
        self._onenote = onenote

    async def handle(self, command: DeleteOneNotePageCommand) -> None:
        GraphIds.check(command.page_id, self._onenote.ID_PATTERN, "page_id")
        if not self._onenote.is_id(command.page_id):
            raise ServiceError(400, "Invalid page_id.")
        await self._runner.run(command.refresh_token, lambda note, broker: self._onenote.delete_page(note, broker, command.page_id))
