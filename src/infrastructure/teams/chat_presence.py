import logging

from outnote import GraphError

from src.application.abstractions.i_chat_presence import IChatPresence
from src.application.abstractions.i_profile_reader import IProfileReader
from src.infrastructure.microsoft.account_cache import AccountCache


class ChatPresence(IChatPresence):
    """The Teams status of the other person in a 1:1 chat. Asking by chat keeps it to people the account already chats with."""

    log = logging.getLogger("schuly.microsoft")
    TTL = 30  # however many tabs poll, Graph is asked this often per chat
    PERSON_TTL = 3600  # who is in a 1:1 chat doesn't change

    def __init__(self, profile: IProfileReader):
        self._profile = profile

    def _other_person(self, note, broker, cache, chat_id: str) -> str | None:
        marker = object()
        hit = cache.get(("chat_other_person", chat_id), marker)
        if hit is not marker:
            return hit
        chat = note.get(f"chats/{chat_id}", {"$expand": "members"}, retry=False)
        me = self._profile.get(note, broker).get("id")
        others = [m.get("userId") for m in chat.get("members") or [] if m.get("userId") and m.get("userId") != me]
        person = others[0] if chat.get("chatType") == "oneOnOne" and len(others) == 1 else None
        cache.set(("chat_other_person", chat_id), person, self.PERSON_TTL)
        return person

    def of_chat(self, note, broker, chat_id: str) -> dict:
        cache = AccountCache.for_broker(broker)
        hit = cache.get(("chat_presence", chat_id))
        if hit is not None:
            return hit
        result = {"availability": None, "activity": None}
        try:
            person = self._other_person(note, broker, cache, chat_id)
            found = note.presences([person]) if person else []
            if found:
                result = {"availability": found[0].get("availability"), "activity": found[0].get("activity")}
        except GraphError as ex:
            # A status is a nicety: without one the header just shows no dot, and the next ask comes after TTL.
            self.log.warning("Teams status unavailable (%s)", ex.status)
        cache.set(("chat_presence", chat_id), result, self.TTL)
        return result
