"""Chat messages as the web renders them: Graph's chatMessage plus `media` (pasted images and
GIFs), `files` (files shared in the chat, with type, size, `kind`, `hasThumbnail` and `webUrl`), `cards` (adaptive cards, polls,
stickers) and `emojis` (Teams and custom emoji, see `IEmojiCatalogue.message_emojis`) pulled out of the body and attachments.

A file's type and size are not on the attachment; they come from the drive item behind its
sharing URL (`shares/u!{url}/driveItem`), looked up in one `$batch` per page and cached per account.
"""

import logging

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
                results = note.batch([GraphPaths.drive_item_path(u, "size,file") for u in todo])
            except Exception:
                results = [None] * len(todo)
            for url, item in zip(todo, results):
                if isinstance(item, dict):
                    meta = {"contentType": (item.get("file") or {}).get("mimeType"), "size": item.get("size")}
                    cache.set(("file_meta", url), meta, self.FILE_META_TTL)
                else:
                    meta = {"contentType": None, "size": None}
                out[url] = meta
        return out

    def enrich(self, note, broker, messages: list[dict]) -> list[dict]:
        files_by_message = {}
        urls = []
        for m in messages:
            files = self._html.reference_files(m)
            files_by_message[id(m)] = files
            urls += [f["contentUrl"] for f in files]
        meta = self.file_meta(note, broker, urls) if urls else {}
        cat = self._catalogue() if any("emoji" in ((m.get("body") or {}).get("content") or "").lower() for m in messages) else None
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
            m.setdefault("importance", "normal")
        return messages

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
