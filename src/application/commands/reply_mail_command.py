from dataclasses import dataclass, field

from mediatorx import ICommand, ICommandHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.services.mail_message_builder import MailMessageBuilder
from src.domain.validation.graph_ids import GraphIds


@dataclass
class ReplyMailCommand(ICommand[None]):
    refresh_token: str = field(repr=False)
    message_id: str
    comment: str
    reply_all: bool


class ReplyMailHandler(ICommandHandler[ReplyMailCommand, None]):
    def __init__(self, accounts: IAccountRunner, builder: MailMessageBuilder):
        self._accounts = accounts
        self._builder = builder

    async def handle(self, command: ReplyMailCommand) -> None:
        GraphIds.check(command.message_id, GraphIds.GRAPH_ID_PATTERN, "message_id")
        self._builder.check_text(command.comment, "comment")
        await self._accounts.run(command.refresh_token, lambda note, broker: note.reply(GraphIds.seg(command.message_id), command.comment, reply_all=command.reply_all))
