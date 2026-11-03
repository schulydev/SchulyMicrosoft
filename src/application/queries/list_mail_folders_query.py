from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.services.mail_folder_tree import MailFolderTree


@dataclass
class ListMailFoldersQuery(IQuery[list[dict]]):
    refresh_token: str = field(repr=False)


class ListMailFoldersHandler(IQueryHandler[ListMailFoldersQuery, list[dict]]):
    def __init__(self, accounts: IAccountRunner, tree: MailFolderTree):
        self._accounts = accounts
        self._tree = tree

    async def handle(self, query: ListMailFoldersQuery) -> list[dict]:
        return await self._accounts.run(query.refresh_token, self._tree.read)
