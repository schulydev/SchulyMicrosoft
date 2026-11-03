from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_one_note import IOneNote
from src.application.abstractions.i_one_note_runner import IOneNoteRunner
from src.domain.errors.service_error import ServiceError
from src.domain.validation.graph_ids import GraphIds


@dataclass
class GetOneNotePageQuery(IQuery[dict]):
    refresh_token: str = field(repr=False)
    page_id: str


class GetOneNotePageHandler(IQueryHandler[GetOneNotePageQuery, dict]):
    def __init__(self, runner: IOneNoteRunner, onenote: IOneNote):
        self._runner = runner
        self._onenote = onenote

    async def handle(self, query: GetOneNotePageQuery) -> dict:
        GraphIds.check(query.page_id, self._onenote.ID_PATTERN, "page_id")
        if not self._onenote.is_id(query.page_id):
            raise ServiceError(400, "Invalid page_id.")
        return await self._runner.run(query.refresh_token, lambda note, broker: self._onenote.page(note, query.page_id))
