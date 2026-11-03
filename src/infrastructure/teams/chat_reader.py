"""Chat messages as the web renders them: Graph's chatMessage plus `media` (pasted images and
GIFs), `files` (files shared in the chat, with type, size, `kind`, `hasThumbnail` and `webUrl`), `cards` (adaptive cards, polls,
stickers) and `emojis` (Teams and custom emoji, see `IEmojiCatalogue.message_emojis`) pulled out of the body and attachments.

A file's type and size are not on the attachment; they come from the drive item behind its
sharing URL (`shares/u!{url}/driveItem`), looked up in one `$batch` per page and cached per account.
"""

import logging

from outnote import GraphError

from src.application.abstractions.i_chat_reader import IChatReader
from src.application.abstractions.i_emoji_catalogue import IEmojiCatalogue
from src.application.abstractions.i_file_thumbnails import IFileThumbnails
from src.application.services.chat_html_sanitizer import ChatHtmlSanitizer
from src.application.services.graph_paths import GraphPaths
from src.infrastructure.microsoft.account_cache import AccountCache


class ChatReader(IChatReader):
    """Chat messages as the web renders them: Graph's chatMessage plus media, files, cards and emojis."""

    log = logging.getLogger("schuly.microsoft")
    FILE_META_TTL = 3600
    FILE_META_RETRY_TTL = 60  # after a failed lookup, so a list refreshed while Graph throttles doesn't ask again each time
    CHAT_FILES_TTL = 6 * 3600
    FILE_REF_TOP = 50

    def __init__(self, html: ChatHtmlSanitizer, emojis: IEmojiCatalogue, thumbnails: IFileThumbnails):
        self._html = html
        self._emojis = emojis
        self._thumbnails = thumbnails

    def file_meta(self, note, broker, urls: list[str]) -> dict[str, dict]:
        """contentUrl -> {contentType, size} (None values when the item can't be read)."""
        cache = AccountCache.for_broker(broker)
        out, todo = {}, []
        for url in dict.fromkeys(urls):
            hit = cache.get(("file_meta", url))
            if hit is not None:
                out[url] = hit
            else:
                todo.append(url)
        if todo:
            try:
                results = note.batch([GraphPaths.drive_item_path(u, "id,size,file,parentReference") for u in todo])
            except Exception:
                results = [None] * len(todo)
            for url, item in zip(todo, results):
                if isinstance(item, dict):
                    meta = {"contentType": (item.get("file") or {}).get("mimeType"), "size": item.get("size")}
                    cache.set(("file_meta", url), meta, self.FILE_META_TTL)
                    self._thumbnails.remember_item(broker, url, item)
                else:
                    meta = {"contentType": None, "size": None}
                    cache.set(("file_meta", url), meta, self.FILE_META_RETRY_TTL)
                out[url] = meta
        return out

    def file_ref(self, note, broker, chat_id: str, message_id: str, attachment_id: str) -> dict | None:
        """A file shared in a message, found by its attachment id. The message list says what each message holds, so this needs no call while that is remembered.

        Graph throttles the single-message read far sooner than the list, and every thumbnail, file and PDF of a chat used to cost one. `chat_message` asks Teams' own API first, which is undocumented and only falls back to that same read, so when it refuses or doesn't know the file, the list gets the last word."""
        cache = AccountCache.for_broker(broker)
        key = ("chat_files", chat_id, message_id)

        def known():
            return next((f for f in cache.get(key) or [] if f.get("id") == attachment_id), None)

        found = known()
        if found:
            return found
        try:
            message = note.chat_message(chat_id, message_id)
            self._remember_files(cache, chat_id, message or {}, self._html.reference_files(message or {}), message_id)
            found = known()
            if found:
                return found
        except GraphError as ex:
            if ex.status != 429:
                raise
            self.log.warning("the chat message read was throttled (Retry-After %s); asking the list", ex.retry_after)
        for message in note.list(f"me/chats/{chat_id}/messages", {"$top": self.FILE_REF_TOP}, limit=self.FILE_REF_TOP, retry=False) or []:
            self._remember_files(cache, chat_id, message, self._html.reference_files(message))
        return known()

    def _remember_files(self, cache, chat_id: str | None, message: dict, files: list[dict], message_id: str | None = None) -> None:
        message_id = message_id or message.get("id")
        chat_id = chat_id or message.get("chatId")
        if files and chat_id and message_id:
            cache.set(("chat_files", chat_id, message_id), files, self.CHAT_FILES_TTL)

    def enrich(self, note, broker, messages: list[dict], chat_id: str | None = None) -> list[dict]:
        files_by_message = {}
        urls = []
        cache = AccountCache.for_broker(broker)
        for m in messages:
            files = self._html.reference_files(m)
            files_by_message[id(m)] = files
            urls += [f["contentUrl"] for f in files]
            self._remember_files(cache, chat_id, m, files)
        meta = self.file_meta(note, broker, urls) if urls else {}
        quotes_by_message = {id(m): self._html.quotes(m) for m in messages}
        cat = self._catalogue() if any("emoji" in ((m.get("body") or {}).get("content") or "").lower() or any("emoji" in (q["content"] or "").lower() for q in quotes_by_message[id(m)]) for m in messages) else None
        for m in messages:
            m["media"] = self._html.media(m)
            m["files"] = [self._file_view({**f, **meta.get(f["contentUrl"], {"contentType": None, "size": None})}) for f in files_by_message[id(m)]]
            body = m.get("body")
            if isinstance(body, dict) and isinstance(body.get("content"), str):
                content, m["emojis"] = self._emojis.message_emojis(body["content"], cat)
                if m["emojis"]:
                    m["body"] = {**body, "content": content}
            else:
                m["emojis"] = []
            m["cards"] = self._html.cards(m)
            m["quotes"] = [self._quote_view(q, cat) for q in quotes_by_message[id(m)]]
            # What a quote needs is in `quotes`; the rest of the raw JSON holds Microsoft's ids, which no caller may get.
            for a in m.get("attachments") or []:
                if a.get("contentType") in self._html.QUOTE_KINDS:
                    a["content"] = None
            m.setdefault("importance", "normal")
        return messages

    def _quote_view(self, quote: dict, cat) -> dict:
        """A quote with its emojis made ready like a message's. `unread` names the fields of a shape Graph documents no further, so the first real one tells what to read; it holds no content."""
        unread = quote.pop("unread", None)
        if unread is not None:
            self.log.warning("quoted message with no readable content; fields: %s", unread)
        content, emojis = self._emojis.message_emojis(quote["content"], cat) if quote["contentType"] == "html" and quote["content"] else (quote["content"], [])
        return {**quote, "content": content, "emojis": emojis}

    def _catalogue(self):
        # Emoji pictures work from the id alone, so a catalogue that can't be loaded only costs the frame counts.
        try:
            return self._emojis.catalogue("default")
        except Exception as ex:
            self.log.info("emoji catalogue unavailable: %s", type(ex).__name__)
            return None

    def _file_view(self, f: dict) -> dict:
        """A chat file with its `kind`, `hasThumbnail` and `webUrl` (the SharePoint / OneDrive link, only when it is one)."""
        kind = self._thumbnails.file_kind(f.get("name"), f.get("contentType"))
        shared = self._thumbnails.is_share_url(f.get("contentUrl"))
        return {**f, "kind": kind, "hasThumbnail": self._thumbnails.has_thumbnail(f.get("contentUrl"), kind), "webUrl": f["contentUrl"] if shared else None}
