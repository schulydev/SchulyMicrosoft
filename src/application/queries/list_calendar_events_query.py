from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_account_runner import IAccountRunner


@dataclass
class ListCalendarEventsQuery(IQuery[list[dict]]):
    refresh_token: str = field(repr=False)
    top: int
    start: str | None
    end: str | None


class ListCalendarEventsHandler(IQueryHandler[ListCalendarEventsQuery, list[dict]]):
    def __init__(self, accounts: IAccountRunner):
        self._accounts = accounts

    async def handle(self, query: ListCalendarEventsQuery) -> list[dict]:
        return await self._accounts.run(query.refresh_token, lambda note, broker: note.events(start=query.start, end=query.end, top=query.top))
