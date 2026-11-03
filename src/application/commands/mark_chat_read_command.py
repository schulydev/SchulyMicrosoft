from dataclasses import dataclass, field

from mediatorx import ICommand, ICommandHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.domain.validation.graph_ids import GraphIds


@dataclass
class MarkChatReadCommand(ICommand[None]):
    refresh_token: str = field(repr=False)
    chat_id: str


class MarkChatReadHandler(ICommandHandler[MarkChatReadCommand, None]):
    def __init__(self, accounts: IAccountRunner):
        self._accounts = accounts

    async def handle(self, command: MarkChatReadCommand) -> None:
        GraphIds.check(command.chat_id, GraphIds.CHAT_ID_PATTERN, "chat_id")
        await self._accounts.run(command.refresh_token, lambda note, broker: note.mark_chat_read(command.chat_id))
