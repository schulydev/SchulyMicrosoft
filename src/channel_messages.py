"""Teams channel posts and their replies, normalized for the web and the MCP tools (read only)."""

from html import unescape

from outnote import html_to_text

from src.teams_files import seg

MAX_TEXT = 4000
PAGE = 50


def _text(body) -> str:
    if not isinstance(body, dict):
        return ""
    content = body.get("content") or ""
    text = unescape(content).strip() if body.get("contentType") == "text" else html_to_text(content)
    return text[:MAX_TEXT]


def _sender(value):
    if not isinstance(value, dict):
        return None
    who = value.get("user") or value.get("application") or value.get("device")
    if not isinstance(who, dict):
        return None
    return {"displayName": who.get("displayName"), "id": who.get("id")}


def normalize(message: dict) -> dict | None:
    """A ChannelMessage, or None for system messages (`messageType` != message) and deleted ones."""
    if not isinstance(message, dict) or message.get("messageType") != "message" or message.get("deletedDateTime"):
        return None
    attachments = [{"name": a.get("name"), "contentType": a.get("contentType"), "webUrl": a.get("contentUrl")} for a in message.get("attachments") or [] if isinstance(a, dict) and a.get("name")]
    return {"id": message.get("id"), "replyToId": message.get("replyToId"), "from": _sender(message.get("from")), "createdDateTime": message.get("createdDateTime"), "lastModifiedDateTime": message.get("lastModifiedDateTime"), "subject": message.get("subject"), "text": _text(message.get("body")), "attachments": attachments, "replyCount": None, "webUrl": message.get("webUrl"), "messageType": "message"}


def _rows(note, path: str, top: int) -> list[dict]:
    rows = note.list(path, {"$top": min(top, PAGE)}, limit=top)
    return [m for m in (normalize(r) for r in rows) if m]


def messages(note, team_id: str, channel_id: str, top: int) -> list[dict]:
    """Top-level posts, newest first (follows nextLink until `top` raw posts were read)."""
    out = _rows(note, f"teams/{seg(team_id)}/channels/{seg(channel_id)}/messages", top)
    return sorted(out, key=lambda m: m.get("createdDateTime") or "", reverse=True)


def replies(note, team_id: str, channel_id: str, message_id: str, top: int) -> list[dict]:
    """Replies to one post, oldest first."""
    out = _rows(note, f"teams/{seg(team_id)}/channels/{seg(channel_id)}/messages/{seg(message_id)}/replies", top)
    return sorted(out, key=lambda m: m.get("createdDateTime") or "")
