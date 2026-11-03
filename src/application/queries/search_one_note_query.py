from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_one_note import IOneNote
from src.application.abstractions.i_one_note_runner import IOneNoteRunner
from src.domain.errors.service_error import ServiceError
from src.domain.validation.graph_ids import GraphIds


@dataclass
class SearchOneNoteQuery(IQuery[dict]):
    refresh_token: str = field(repr=False)
    q: str
    notebook: str | None
    top: int


class SearchOneNoteHandler(IQueryHandler[SearchOneNoteQuery, dict]):
    def __init__(self, runner: IOneNoteRunner, onenote: IOneNote):
        self._runner = runner
        self._onenote = onenote

    async def handle(self, query: SearchOneNoteQuery) -> dict:
        if not query.q.strip():
            raise ServiceError(400, "q is empty.")
        if query.notebook:
            GraphIds.check(query.notebook, self._onenote.ID_PATTERN, "notebook")
            if not self._onenote.is_id(query.notebook):
                raise ServiceError(400, "Invalid notebook.")
        return await self._runner.run(query.refresh_token, lambda note, broker: self._onenote.search(note, broker, query.q, query.notebook, query.top))
