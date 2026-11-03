"""Well-known mail folder roles.

Graph lists mail folders by display name, which is in the mailbox language ("Posteingang",
"Gesendete Elemente", ...). Each well-known folder is also addressable by its fixed name
(`me/mailFolders/inbox`), so one `$batch` of those lookups maps folder ids to roles. The map is
cached per account for an hour; a name the mailbox lacks (404) is simply absent.
"""


from src.application.abstractions.i_mail_folder_roles import IMailFolderRoles
from src.infrastructure.microsoft.account_cache import AccountCache


class MailFolderRoles(IMailFolderRoles):
    """Well-known mail folder names, looked up with one $batch and cached per account."""

    WELL_KNOWN_NAMES = ("inbox", "drafts", "sentitems", "deleteditems", "junkemail", "archive", "outbox", "conversationhistory", "syncissues", "conflicts", "localfailures", "serverfailures", "rssfeeds")
    ROLES_TTL = 3600
    CACHE_KEY = "mail_folder_roles"

    def lookup(self, note) -> dict[str, str]:
        """folder id -> well-known name, from one Graph $batch (13 requests, under the 20 per batch limit)."""
        results = note.batch([f"me/mailFolders/{name}?$select=id" for name in self.WELL_KNOWN_NAMES])
        roles = {}
        for name, result in zip(self.WELL_KNOWN_NAMES, results):
            if isinstance(result, dict) and isinstance(result.get("id"), str):
                roles.setdefault(result["id"], name)
        return roles

    def cached(self, broker) -> dict[str, str] | None:
        return AccountCache.for_broker(broker).get(self.CACHE_KEY)

    def remember(self, broker, roles: dict[str, str]):
        # An empty map means the lookup failed (every mailbox has an inbox); try again on the next list.
        if roles:
            AccountCache.for_broker(broker).set(self.CACHE_KEY, roles, self.ROLES_TTL)
