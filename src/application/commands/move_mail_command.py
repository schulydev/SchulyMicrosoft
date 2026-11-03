from dataclasses import dataclass, field

from mediatorx import ICommand, ICommandHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.domain.validation.graph_ids import GraphIds


@dataclass
class MoveMailCommand(ICommand[dict]):
    refresh_token: str = field(repr=False)
    message_id: str
    folder: str


class MoveMailHandler(ICommandHandler[MoveMailCommand, dict]):
    def __init__(self, accounts: IAccountRunner):
        self._accounts = accounts

    async def handle(self, command: MoveMailCommand) -> dict:
        GraphIds.check(command.message_id, GraphIds.GRAPH_ID_PATTERN, "message_id")
        GraphIds.check(command.folder, GraphIds.GRAPH_ID_PATTERN, "folder")
        return await self._accounts.run(command.refresh_token, lambda note, broker: note.move_email(GraphIds.seg(command.message_id), GraphIds.seg(command.folder)))
