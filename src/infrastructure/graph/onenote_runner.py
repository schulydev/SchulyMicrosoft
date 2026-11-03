from collections.abc import Callable

from outnote import GraphError

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.abstractions.i_one_note_runner import IOneNoteRunner
from src.domain.errors.service_error import ServiceError


class OneNoteRunner(IOneNoteRunner):
    """Graph's refusals for OneNote calls, mapped before the account runner sees them."""

    def __init__(self, accounts: IAccountRunner):
        self._accounts = accounts

    async def run(self, refresh_token: str, action: Callable[..., object]) -> object:
        def run(note, broker):
            try:
                return action(note, broker)
            except GraphError as ex:
                if ex.status == 403:
                    raise ServiceError(403, "OneNote refused access to this notebook.")
                if ex.status in (400, 409, 422):
                    raise ServiceError(422, f"OneNote refused the request: {str(ex)[:200]}")
                raise

        return await self._accounts.run(refresh_token, run)
