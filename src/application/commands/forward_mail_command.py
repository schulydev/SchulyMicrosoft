from dataclasses import dataclass, field

from mediatorx import ICommand, ICommandHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.services.mail_message_builder import MailMessageBuilder
from src.domain.errors.service_error import ServiceError
from src.domain.validation.graph_ids import GraphIds


@dataclass
class ForwardMailCommand(ICommand[None]):
    refresh_token: str = field(repr=False)
    message_id: str
    to: list[str]
    comment: str


class ForwardMailHandler(ICommandHandler[ForwardMailCommand, None]):
    def __init__(self, accounts: IAccountRunner, builder: MailMessageBuilder):
        self._accounts = accounts
        self._builder = builder

    async def handle(self, command: ForwardMailCommand) -> None:
        GraphIds.check(command.message_id, GraphIds.GRAPH_ID_PATTERN, "message_id")
        self._builder.check_text(command.comment, "comment")
        to = self._builder.addresses(command.to, "to")
        if not to:
            raise ServiceError(400, "At least one recipient is required.")
        if len(to) > self._builder.MAX_RECIPIENTS:
            raise ServiceError(400, f"At most {self._builder.MAX_RECIPIENTS} recipients are allowed.")
        await self._accounts.run(command.refresh_token, lambda note, broker: note.forward(GraphIds.seg(command.message_id), to, command.comment))
