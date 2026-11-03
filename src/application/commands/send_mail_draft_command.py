from dataclasses import dataclass, field

from mediatorx import ICommand, ICommandHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.domain.validation.graph_ids import GraphIds


@dataclass
class SendMailDraftCommand(ICommand[None]):
    refresh_token: str = field(repr=False)
    message_id: str


class SendMailDraftHandler(ICommandHandler[SendMailDraftCommand, None]):
    def __init__(self, accounts: IAccountRunner):
        self._accounts = accounts

    async def handle(self, command: SendMailDraftCommand) -> None:
        GraphIds.check(command.message_id, GraphIds.GRAPH_ID_PATTERN, "message_id")
        await self._accounts.run(command.refresh_token, lambda note, broker: note.send_draft(GraphIds.seg(command.message_id)))
