from dataclasses import dataclass, field

from mediatorx import ICommand, ICommandHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.domain.validation.graph_ids import GraphIds


@dataclass
class DeleteMailCommand(ICommand[None]):
    refresh_token: str = field(repr=False)
    message_id: str


class DeleteMailHandler(ICommandHandler[DeleteMailCommand, None]):
    def __init__(self, accounts: IAccountRunner):
        self._accounts = accounts

    async def handle(self, command: DeleteMailCommand) -> None:
        GraphIds.check(command.message_id, GraphIds.GRAPH_ID_PATTERN, "message_id")
        await self._accounts.run(command.refresh_token, lambda note, broker: note.delete_email(GraphIds.seg(command.message_id)))
