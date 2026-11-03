from dataclasses import dataclass, field

from mediatorx import ICommand, ICommandHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.dtos.mail_message_in import MailMessageIn
from src.application.services.mail_message_builder import MailMessageBuilder


@dataclass
class CreateMailDraftCommand(ICommand[dict]):
    refresh_token: str = field(repr=False)
    body: MailMessageIn


class CreateMailDraftHandler(ICommandHandler[CreateMailDraftCommand, dict]):
    def __init__(self, accounts: IAccountRunner, builder: MailMessageBuilder):
        self._accounts = accounts
        self._builder = builder

    async def handle(self, command: CreateMailDraftCommand) -> dict:
        args = self._builder.message_args(command.body)
        return await self._accounts.run(command.refresh_token, lambda note, broker: note.create_draft(**args))
