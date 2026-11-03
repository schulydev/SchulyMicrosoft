from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.domain.errors.service_error import ServiceError
from src.domain.validation.graph_ids import GraphIds


@dataclass
class ListMailQuery(IQuery[list[dict]]):
    refresh_token: str = field(repr=False)
    folder: str
    top: int
    skip: int
    unread: bool
    search: str | None


class ListMailHandler(IQueryHandler[ListMailQuery, list[dict]]):
    # Field lists keep list responses small: no mail body in lists (the single-message route returns it).
    # Explicit, not OutNote's default list fields: the web's mail list shows `toRecipients`, which that default leaves out.
    MAIL_LIST_FIELDS = "id,subject,from,toRecipients,receivedDateTime,bodyPreview,isRead,flag,hasAttachments,importance,conversationId"

    def __init__(self, accounts: IAccountRunner):
        self._accounts = accounts

    async def handle(self, query: ListMailQuery) -> list[dict]:
        GraphIds.check(query.folder, GraphIds.GRAPH_ID_PATTERN, "folder")
        if query.skip and query.search:
            raise ServiceError(400, "skip cannot be combined with search.")
        folder = GraphIds.seg(query.folder)
        if not query.skip:
            return await self._accounts.run(query.refresh_token, lambda note, broker: note.emails(folder=folder, top=query.top, unread=query.unread, search=query.search, select=self.MAIL_LIST_FIELDS))
        # Paging: newest first, `skip` messages in. Graph does not allow $skip together with $search.
        params = {"$top": min(query.top, 100), "$skip": query.skip, "$select": self.MAIL_LIST_FIELDS, "$orderby": "receivedDateTime desc"}
        if query.unread:
            params["$filter"] = "isRead eq false"
        return await self._accounts.run(query.refresh_token, lambda note, broker: note.list(f"me/mailFolders/{folder}/messages", params, limit=query.top))
