from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.abstractions.i_chat_live import IChatLive
from src.application.options.microsoft_options import MicrosoftOptions
from src.domain.validation.refresh_token_format import RefreshTokenFormat


@dataclass
class OpenChatLiveQuery(IQuery[AsyncIterator[bytes]]):
    refresh_token: str = field(repr=False)


class OpenChatLiveHandler(IQueryHandler[OpenChatLiveQuery, AsyncIterator[bytes]]):
    def __init__(self, accounts: IAccountRunner, live: IChatLive, options: MicrosoftOptions):
        self._accounts = accounts
        self._live = live
        self._options = options

    async def handle(self, query: OpenChatLiveQuery) -> AsyncIterator[bytes]:
        RefreshTokenFormat.check(query.refresh_token)

        def run(note, broker):
            # A dead sign-in is refused here, as a real status, before the stream starts.
            broker(self._options.device_client_id)
            return self._live.open(note, broker)

        return await self._accounts.run(query.refresh_token, run)
