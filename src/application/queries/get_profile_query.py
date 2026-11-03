from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.abstractions.i_profile_reader import IProfileReader


@dataclass
class GetProfileQuery(IQuery[dict]):
    refresh_token: str = field(repr=False)


class GetProfileHandler(IQueryHandler[GetProfileQuery, dict]):
    def __init__(self, accounts: IAccountRunner, profile: IProfileReader):
        self._accounts = accounts
        self._profile = profile

    async def handle(self, query: GetProfileQuery) -> dict:
        return await self._accounts.run(query.refresh_token, self._profile.get)
