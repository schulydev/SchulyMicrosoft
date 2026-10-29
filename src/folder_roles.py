"""Well-known mail folder roles.

Graph lists mail folders by display name, which is in the mailbox language ("Posteingang",
"Gesendete Elemente", ...). Each well-known folder is also addressable by its fixed name
(`me/mailFolders/inbox`), so one `$batch` of those lookups maps folder ids to roles. The map is
cached per account for an hour; a name the mailbox lacks (404) is simply absent.
"""

from src.account_cache import for_broker

WELL_KNOWN_NAMES = ("inbox", "drafts", "sentitems", "deleteditems", "junkemail", "archive", "outbox", "conversationhistory", "syncissues", "conflicts", "localfailures", "serverfailures", "rssfeeds")
ROLES_TTL = 3600
CACHE_KEY = "mail_folder_roles"


def lookup(note) -> dict[str, str]:
    """folder id -> well-known name, from one Graph $batch (13 requests, under the 20 per batch limit)."""
    results = note.batch([f"me/mailFolders/{name}?$select=id" for name in WELL_KNOWN_NAMES])
    roles = {}
    for name, result in zip(WELL_KNOWN_NAMES, results):
        if isinstance(result, dict) and isinstance(result.get("id"), str):
            roles.setdefault(result["id"], name)
    return roles


def cached(broker) -> dict[str, str] | None:
    return for_broker(broker).get(CACHE_KEY)


def remember(broker, roles: dict[str, str]):
    # An empty map means the lookup failed (every mailbox has an inbox); try again on the next list.
    if roles:
        for_broker(broker).set(CACHE_KEY, roles, ROLES_TTL)
