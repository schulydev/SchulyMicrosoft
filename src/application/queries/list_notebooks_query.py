from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_account_runner import IAccountRunner


@dataclass
class ListNotebooksQuery(IQuery[list[dict]]):
    refresh_token: str = field(repr=False)


class ListNotebooksHandler(IQueryHandler[ListNotebooksQuery, list[dict]]):
    def __init__(self, accounts: IAccountRunner):
        self._accounts = accounts

    async def handle(self, query: ListNotebooksQuery) -> list[dict]:
        return await self._accounts.run(query.refresh_token, lambda note, broker: note.notebooks())
