import logging
from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.abstractions.i_teams_chat import ITeamsChat


@dataclass
class ListChatsQuery(IQuery[list[dict]]):
    refresh_token: str = field(repr=False)
    top: int


class ListChatsHandler(IQueryHandler[ListChatsQuery, list[dict]]):
    CHAT_FIELDS = "id,topic,chatType,createdDateTime,lastUpdatedDateTime,webUrl,viewpoint"
    log = logging.getLogger("schuly.microsoft")

    def __init__(self, accounts: IAccountRunner, teams_chat: ITeamsChat):
        self._accounts = accounts
        self._teams_chat = teams_chat

    async def handle(self, query: ListChatsQuery) -> list[dict]:
        def fetch(note, broker):
            items = note.list("me/chats", {"$top": min(query.top, 50), "$select": self.CHAT_FIELDS, "$expand": "members,lastMessagePreview", "$orderby": "lastMessagePreview/createdDateTime desc"}, limit=query.top)
            try:
                return self._teams_chat.mark_images(broker, items)
            except Exception as ex:
                # The picture flag is a nicety; the chat list never fails over it.
                self.log.info("chat picture lookup failed: %s", type(ex).__name__)
                for item in items:
                    item["hasImage"] = False
                return items

        return await self._accounts.run(query.refresh_token, fetch)
