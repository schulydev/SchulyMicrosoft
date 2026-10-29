"""Chat messages as the web renders them: Graph's chatMessage plus `media` (pasted images and
GIFs), `files` (files shared in the chat, with type and size) and `cards` (adaptive cards, polls,
stickers) pulled out of the body and attachments.

A file's type and size are not on the attachment; they come from the drive item behind its
sharing URL (`shares/u!{url}/driveItem`), looked up in one `$batch` per page and cached per account.
"""

import base64
from urllib.parse import quote

from src import chat_html
from src.account_cache import for_broker

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
    for m in messages:
        m["media"] = chat_html.media(m)
        m["files"] = [{**f, **meta.get(f["contentUrl"], {"contentType": None, "size": None})} for f in files_by_message[id(m)]]
        m["cards"] = chat_html.cards(m)
        m.setdefault("importance", "normal")
    return messages


def message_path(chat_id: str, message_id: str) -> str:
    return f"chats/{chat_id}/messages/{quote(message_id, safe='')}"
