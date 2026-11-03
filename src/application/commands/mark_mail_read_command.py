from dataclasses import dataclass, field

from mediatorx import ICommand, ICommandHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.domain.validation.graph_ids import GraphIds


@dataclass
class MarkMailReadCommand(ICommand[dict]):
    refresh_token: str = field(repr=False)
    message_id: str
    read: bool


class MarkMailReadHandler(ICommandHandler[MarkMailReadCommand, dict]):
    def __init__(self, accounts: IAccountRunner):
        self._accounts = accounts

    async def handle(self, command: MarkMailReadCommand) -> dict:
        GraphIds.check(command.message_id, GraphIds.GRAPH_ID_PATTERN, "message_id")
        return await self._accounts.run(command.refresh_token, lambda note, broker: note.mark_read(GraphIds.seg(command.message_id), command.read) or {"isRead": command.read})
