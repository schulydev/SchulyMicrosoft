"""Posting a chat message the way Teams does: sanitized HTML, @mentions, inline images as hosted
contents, a GIF, and files shared through the sender's OneDrive.

Files follow the Teams client: upload to `Microsoft Teams Chat Files/` in the sender's OneDrive
(an upload session in 320 KiB-multiple chunks above 4 MB), grant the chat members read access
without an e-mail, then reference the file in the message (`<attachment id="GUID">` + a
`reference` attachment whose id is the GUID from the drive item's eTag).
"""

import base64
import re
from urllib.parse import quote
from entrance import http_client

from src.application.abstractions.i_chat_sender import IChatSender
from src.application.abstractions.i_emoji_catalogue import IEmojiCatalogue
from src.application.abstractions.i_profile_reader import IProfileReader
from src.application.services.chat_html_sanitizer import ChatHtmlSanitizer
from src.application.services.image_sniffer import ImageSniffer
from src.domain.chat.chat_send_limits import ChatSendLimits
from src.domain.chat.outgoing_message import OutgoingMessage
from src.domain.chat.upload import Upload
from src.domain.errors.emoji_error import EmojiError
from src.domain.errors.send_error import SendError


class ChatSender(IChatSender):
    """Posting a chat message the way Teams does: sanitized HTML, mentions, hosted images, a GIF and shared files."""

    MAX_CONTENT_CHARS = 28000  # Graph's chat message body limit is about 28 KB
    MAX_IMAGES_BYTES = 3 * 1024 * 1024  # about 4 MB once base64-encoded, Graph's request limit
    MAX_IMAGES = ChatSendLimits.MAX_IMAGES
    MAX_FILE_BYTES = 100 * 1024 * 1024
    MAX_FILES = ChatSendLimits.MAX_FILES
    MAX_MENTIONS = 20
    SIMPLE_UPLOAD_MAX = 4 * 1024 * 1024
    UPLOAD_CHUNK = 10 * 320 * 1024  # upload sessions take chunks in multiples of 320 KiB
    CHAT_FILES_FOLDER = "Microsoft Teams Chat Files"
    SELF_CHAT = "48:notes"
    IMPORTANCE = ("normal", "high", "urgent")
    GUID_IN_ETAG = re.compile(r"\{([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})\}")
    USER_ID = re.compile(r"[A-Za-z0-9@._-]{1,200}")
    http_client = staticmethod(http_client)

    def __init__(self, html: ChatHtmlSanitizer, emojis: IEmojiCatalogue, profile: IProfileReader):
        self._html = html
        self._emojis = emojis
        self._profile = profile

    def safe_name(self, name: str | None) -> str:
        cleaned = re.sub(r'[\x00-\x1f\x7f\\/:*?"<>|#%]', "_", name or "")
        return cleaned.strip(" .")[:200] or "file"

    def validate(self, msg: OutgoingMessage) -> OutgoingMessage:
        if msg.content_type not in ("text", "html"):
            raise SendError(400, "contentType must be text or html.")
        if len(msg.content) > self.MAX_CONTENT_CHARS:
            raise SendError(413, f"The message may be at most {self.MAX_CONTENT_CHARS} characters.")
        if msg.importance is not None and msg.importance not in self.IMPORTANCE:
            raise SendError(400, "importance must be normal, high or urgent.")
        if len(msg.mentions) > self.MAX_MENTIONS:
            raise SendError(400, f"At most {self.MAX_MENTIONS} mentions are allowed.")
        clean = []
        for m in msg.mentions:
            user = ((m or {}).get("mentioned") or {}).get("user") or {}
            mid, uid, text = (m or {}).get("id"), user.get("id"), (m or {}).get("mentionText")
            if not isinstance(mid, int) or not 0 <= mid < self.MAX_MENTIONS or not isinstance(uid, str) or not self.USER_ID.fullmatch(uid) or not isinstance(text, str) or not 0 < len(text) <= 200:
                raise SendError(400, "Invalid mention.")
            clean.append({"id": mid, "mentionText": text, "mentioned": {"user": {"id": uid, "displayName": str(user.get("displayName") or text)[:200], "userIdentityType": "aadUser"}}})
        msg.mentions = clean
        if msg.gif is not None:
            url = msg.gif.get("url") if isinstance(msg.gif, dict) else None
            if not isinstance(url, str) or len(url) > 2000 or not self._html.is_gif_host(url):
                raise SendError(400, "gif.url must be an https Giphy or Tenor media URL.")
        if len(msg.images) > self.MAX_IMAGES:
            raise SendError(400, f"At most {self.MAX_IMAGES} images are allowed.")
        if sum(i.size for i in msg.images) > self.MAX_IMAGES_BYTES:
            raise SendError(413, "Inline images may total at most 3 MB; send larger ones as files.")
        if len(msg.files) > self.MAX_FILES:
            raise SendError(400, f"At most {self.MAX_FILES} files are allowed.")
        for f in msg.files:
            if f.size > self.MAX_FILE_BYTES:
                raise SendError(413, "A file may be at most 100 MB.")
        if not msg.content.strip() and not msg.gif and not msg.images and not msg.files:
            raise SendError(400, "The message is empty.")
        return msg

    def _hosted_contents(self, images: list[Upload]) -> list[dict]:
        out = []
        for n, image in enumerate(images, start=1):
            data = image.file.read(self.MAX_IMAGES_BYTES + 1)
            mime = ImageSniffer.chat_image(data[:12])
            if mime is None:
                raise SendError(415, "Inline images must be PNG, JPEG, GIF or WEBP.")
            out.append({"@microsoft.graph.temporaryId": str(n), "contentBytes": base64.b64encode(data).decode(), "contentType": mime})
        return out

    def payload(self, msg: OutgoingMessage, attachments: list[dict] | None = None) -> dict:
        """The Graph chatMessage body for `msg` (files already uploaded into `attachments`)."""
        attachments = attachments or []
        rich = msg.content_type == "html" or msg.mentions or msg.gif or msg.images or attachments
        if not rich:
            body = {"contentType": "text", "content": msg.content}
            mentions = []
        else:
            image_ids = set(range(1, len(msg.images) + 1))
            if msg.content_type == "html":
                try:
                    content, used_mentions, used_images = self._html.sanitize(msg.content, {m["id"] for m in msg.mentions}, image_ids, self._emojis.for_send)
                except EmojiError as ex:
                    raise SendError(503, f"Emoji can't be sent right now: {ex}") from None
            else:
                content, used_mentions, used_images = self._html.text_to_html(msg.content), set(), set()
            # Graph refuses a mention without its <at> tag, so mentions the body doesn't reference are dropped.
            mentions = [m for m in msg.mentions if m["id"] in used_mentions]
            parts = [content] if content else []
            parts += [f'<p><img src="../hostedContents/{n}/$value"></p>' for n in sorted(image_ids - used_images)]
            if msg.gif:
                parts.append(self._html.gif_html(msg.gif["url"], msg.gif.get("alt"), self._dim(msg.gif.get("width")), self._dim(msg.gif.get("height"))))
            parts += [f'<attachment id="{a["id"]}"></attachment>' for a in attachments]
            body = {"contentType": "html", "content": "".join(parts)}
        out = {"body": body}
        if mentions:
            out["mentions"] = mentions
        if msg.importance:
            out["importance"] = msg.importance
        if msg.images:
            out["hostedContents"] = self._hosted_contents(msg.images)
        if attachments:
            out["attachments"] = attachments
        return out

    def _dim(self, value) -> int | None:
        return value if isinstance(value, int) and 0 < value <= 4096 else None

    def upload_file(self, note, upload: Upload) -> dict:
        """Uploads into the sender's `Microsoft Teams Chat Files` folder (renaming on a clash); returns the driveItem."""
        target = f"me/drive/root:/{quote(self.CHAT_FILES_FOLDER, safe='')}/{quote(self.safe_name(upload.name), safe='')}:"
        if upload.size <= self.SIMPLE_UPLOAD_MAX:
            data = upload.file.read(self.SIMPLE_UPLOAD_MAX + 1)
            return note.put(f"{target}/content?@microsoft.graph.conflictBehavior=rename", data, content_type=upload.content_type or "application/octet-stream")
        session = note.post(f"{target}/createUploadSession", {"item": {"@microsoft.graph.conflictBehavior": "rename"}})
        url = session["uploadUrl"]
        client = self.http_client()
        sent, item = 0, None
        try:
            while sent < upload.size:
                chunk = upload.file.read(min(self.UPLOAD_CHUNK, upload.size - sent))
                if not chunk:
                    raise SendError(400, "The file ended before its declared size.")
                # The session URL is pre-authorized; it must not carry the Graph bearer token.
                r = client.request("PUT", url, content=chunk, headers={"Content-Length": str(len(chunk)), "Content-Range": f"bytes {sent}-{sent + len(chunk) - 1}/{upload.size}"}, timeout=120)
                if r.status_code >= 400:
                    raise SendError(502, f"OneDrive refused the upload ({r.status_code}).")
                sent += len(chunk)
                if r.status_code in (200, 201):
                    item = r.json()
        except BaseException:
            try:
                client.request("DELETE", url, timeout=15)
            except Exception:
                pass
            raise
        if not item:
            raise SendError(502, "OneDrive did not confirm the upload.")
        return item

    def chat_member_ids(self, note, broker, chat_id: str) -> list[str]:
        if chat_id == self.SELF_CHAT:
            return []
        me = self._profile.get(note, broker).get("id")
        ids = []
        for m in note.list(f"chats/{chat_id}/members"):
            uid = m.get("userId")
            if isinstance(uid, str) and uid != me and uid not in ids:
                ids.append(uid)
        return ids

    def share_with(self, note, item_id: str, member_ids: list[str]):
        if not member_ids:
            return
        note.post(f"me/drive/items/{quote(item_id, safe='')}/invite", {"recipients": [{"objectId": uid} for uid in member_ids], "roles": ["read"], "requireSignIn": True, "sendInvitation": False})

    def reference_attachment(self, item: dict) -> dict:
        m = self.GUID_IN_ETAG.search(item.get("eTag") or "")
        if not m or not item.get("webUrl"):
            raise SendError(502, "OneDrive returned an item without an eTag GUID or webUrl.")
        return {"id": m.group(1).lower(), "contentType": "reference", "contentUrl": item["webUrl"], "name": item.get("name")}

    def send(self, note, broker, chat_id: str, msg: OutgoingMessage) -> dict:
        attachments = []
        if msg.files:
            members = self.chat_member_ids(note, broker, chat_id)
            for upload in msg.files:
                item = self.upload_file(note, upload)
                self.share_with(note, item["id"], members)
                attachments.append(self.reference_attachment(item))
        return note.post(f"chats/{quote(chat_id, safe=':@.=-_')}/messages", self.payload(msg, attachments))
