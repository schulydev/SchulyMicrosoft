from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_one_note import IOneNote
from src.application.abstractions.i_one_note_runner import IOneNoteRunner


@dataclass
class ListOneNoteNotebooksQuery(IQuery[list[dict]]):
    refresh_token: str = field(repr=False)
    teams: bool


class ListOneNoteNotebooksHandler(IQueryHandler[ListOneNoteNotebooksQuery, list[dict]]):
    def __init__(self, runner: IOneNoteRunner, onenote: IOneNote):
        self._runner = runner
        self._onenote = onenote

    async def handle(self, query: ListOneNoteNotebooksQuery) -> list[dict]:
        return await self._runner.run(query.refresh_token, lambda note, broker: self._onenote.notebooks(note, broker, query.teams))
