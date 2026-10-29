"""Chat messages as the web renders them: Graph's chatMessage plus `media` (pasted images and
GIFs), `files` (files shared in the chat, with type, size, `kind`, `hasThumbnail` and `webUrl`), `cards` (adaptive cards, polls,
stickers) and `emojis` (Teams and custom emoji, see `emojis.message_emojis`) pulled out of the body and attachments.

A file's type and size are not on the attachment; they come from the drive item behind its
sharing URL (`shares/u!{url}/driveItem`), looked up in one `$batch` per page and cached per account.
"""

import base64
import logging
from urllib.parse import quote

from src import chat_html, emojis, file_thumbs
from src.account_cache import for_broker

log = logging.getLogger("schuly.microsoft")
FILE_META_TTL = 3600
DRIVE_ITEM_FIELDS = "id,name,size,file,webUrl"


def share_id(url: str) -> str:
    return "u!" + base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")


def drive_item_path(url: str, select: str = DRIVE_ITEM_FIELDS) -> str:
    return f"shares/{share_id(url)}/driveItem?$select={select}"


def file_meta(note, broker, urls: list[str]) -> dict[str, dict]:
    """contentUrl -> {contentType, size} (None values when the item can't be read)."""
    cache = for_broker(broker)
    out, todo = {}, []
    for url in dict.fromkeys(urls):
        hit = cache.get(("file_meta", url))
        if hit is not None:
            out[url] = hit
        else:
            todo.append(url)
    if todo:
        try:
            results = note.batch([drive_item_path(u, "size,file") for u in todo])
        except Exception:
            results = [None] * len(todo)
        for url, item in zip(todo, results):
            if isinstance(item, dict):
                meta = {"contentType": (item.get("file") or {}).get("mimeType"), "size": item.get("size")}
                cache.set(("file_meta", url), meta, FILE_META_TTL)
            else:
                meta = {"contentType": None, "size": None}
            out[url] = meta
    return out


def enrich(note, broker, messages: list[dict]) -> list[dict]:
    files_by_message = {}
    urls = []
    for m in messages:
        files = chat_html.reference_files(m)
        files_by_message[id(m)] = files
        urls += [f["contentUrl"] for f in files]
    meta = file_meta(note, broker, urls) if urls else {}
    cat = _catalogue() if any("emoji" in ((m.get("body") or {}).get("content") or "").lower() for m in messages) else None
    for m in messages:
        m["media"] = chat_html.media(m)
        m["files"] = [_file_view({**f, **meta.get(f["contentUrl"], {"contentType": None, "size": None})}) for f in files_by_message[id(m)]]
        body = m.get("body")
        if isinstance(body, dict) and isinstance(body.get("content"), str):
            content, m["emojis"] = emojis.message_emojis(body["content"], cat)
            if m["emojis"]:
                m["body"] = {**body, "content": content}
        else:
            m["emojis"] = []
        m["cards"] = chat_html.cards(m)
        m.setdefault("importance", "normal")
    return messages


def _catalogue():
    # Emoji pictures work from the id alone, so a catalogue that can't be loaded only costs the frame counts.
    try:
        return emojis.catalogue("default")
    except Exception as ex:
        log.info("emoji catalogue unavailable: %s", type(ex).__name__)
        return None


def _file_view(f: dict) -> dict:
    """A chat file with its `kind`, `hasThumbnail` and `webUrl` (the SharePoint / OneDrive link, only when it is one)."""
    kind = file_thumbs.file_kind(f.get("name"), f.get("contentType"))
    shared = file_thumbs.is_share_url(f.get("contentUrl"))
    return {**f, "kind": kind, "hasThumbnail": file_thumbs.has_thumbnail(f.get("contentUrl"), kind), "webUrl": f["contentUrl"] if shared else None}


def message_path(chat_id: str, message_id: str) -> str:
    return f"chats/{chat_id}/messages/{quote(message_id, safe='')}"
