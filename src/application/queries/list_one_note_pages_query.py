from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_one_note import IOneNote
from src.application.abstractions.i_one_note_runner import IOneNoteRunner
from src.domain.errors.service_error import ServiceError
from src.domain.validation.graph_ids import GraphIds


@dataclass
class ListOneNotePagesQuery(IQuery[dict]):
    refresh_token: str = field(repr=False)
    section_id: str
    top: int
    skip: int


class ListOneNotePagesHandler(IQueryHandler[ListOneNotePagesQuery, dict]):
    def __init__(self, runner: IOneNoteRunner, onenote: IOneNote):
        self._runner = runner
        self._onenote = onenote

    async def handle(self, query: ListOneNotePagesQuery) -> dict:
        GraphIds.check(query.section_id, self._onenote.ID_PATTERN, "section_id")
        if not self._onenote.is_id(query.section_id):
            raise ServiceError(400, "Invalid section_id.")
        return await self._runner.run(query.refresh_token, lambda note, broker: self._onenote.pages(note, query.section_id, query.top, query.skip))
