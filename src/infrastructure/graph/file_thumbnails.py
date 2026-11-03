"""File kinds and thumbnails for files shared in chats and for OneDrive items.

A file shared in a chat is a `reference` attachment whose `contentUrl` is a SharePoint / OneDrive link. Graph turns that link into
its drive item (`shares/{u!base64url(url)}/driveItem`), and the item has thumbnails (`thumbnails/0/{small|medium|large}/content`) for
Office documents, PDFs, images and videos. The resolved item ids are cached per account for an hour.

Only SharePoint / OneDrive hosts are accepted (`*.sharepoint.com` by suffix, `onedrive.live.com` and `1drv.ms` exactly), https only.
"""

import posixpath
import re
from urllib.parse import quote, urlsplit
from outnote import GraphError

from src.application.abstractions.i_file_thumbnails import IFileThumbnails
from src.application.services.graph_paths import GraphPaths
from src.infrastructure.microsoft.account_cache import AccountCache


class FileThumbnails(IFileThumbnails):
    """File kinds, the SharePoint / OneDrive host check, and thumbnails of chat files and drive items."""

    ITEM_TTL = 3600
    SIZES = ("small", "medium", "large")
    EXACT_HOSTS = frozenset({"onedrive.live.com", "1drv.ms"})
    HOST_SUFFIXES = (".sharepoint.com",)
    GRAPH_ID = re.compile(r"[A-Za-z0-9!=_\-+.]{1,512}")
    MAX_THUMBNAIL_BYTES = 2 * 1024 * 1024
    KINDS_BY_EXTENSION = {
        "word": {"doc", "docx", "docm", "dot", "dotx", "odt", "rtf"},
        "excel": {"xls", "xlsx", "xlsm", "xlsb", "xlt", "xltx", "ods", "csv"},
        "powerpoint": {"ppt", "pptx", "pptm", "pps", "ppsx", "odp"},
        "pdf": {"pdf"},
        "onenote": {"one", "onetoc2"},
        "image": {"png", "jpg", "jpeg", "gif", "webp", "bmp", "svg", "heic", "tif", "tiff", "ico", "avif"},
        "video": {"mp4", "mov", "mkv", "webm", "avi", "m4v", "wmv", "mpg", "mpeg"},
        "audio": {"mp3", "wav", "m4a", "ogg", "oga", "flac", "aac", "wma", "opus"},
        "archive": {"zip", "rar", "7z", "tar", "gz", "tgz", "bz2", "xz"},
        "code": {"py", "js", "ts", "tsx", "jsx", "java", "cs", "c", "cpp", "h", "hpp", "go", "rs", "rb", "php", "sh", "ps1", "json", "xml", "yml", "yaml", "html", "htm", "css", "scss", "sql", "kt", "swift", "dart", "lua", "ipynb", "md"},
        "text": {"txt", "log", "ini", "cfg", "conf", "tex"},
    }
    EXTENSION_KIND = {ext: kind for kind, exts in KINDS_BY_EXTENSION.items() for ext in exts}
    THUMBNAIL_KINDS = frozenset({"word", "excel", "powerpoint", "pdf", "image", "video", "text"})

    def is_share_url(self, url) -> bool:
        """True only for an https SharePoint / OneDrive link (no credentials, default port)."""
        if not isinstance(url, str) or not url or len(url) > 4000 or any(ord(c) < 33 for c in url):
            return False
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            return False
        host = (parts.hostname or "").lower()
        return parts.scheme == "https" and port in (None, 443) and not parts.username and not parts.password and (host in self.EXACT_HOSTS or any(host.endswith(s) for s in self.HOST_SUFFIXES))

    def file_kind(self, name, mime) -> str:
        """word | excel | powerpoint | pdf | onenote | image | video | audio | archive | code | text | other, from the extension, then the MIME type."""
        ext = posixpath.splitext(name or "")[1].lstrip(".").lower() if isinstance(name, str) else ""
        if ext in self.EXTENSION_KIND:
            return self.EXTENSION_KIND[ext]
        mime = (mime or "").split(";")[0].strip().lower() if isinstance(mime, str) else ""
        major = mime.split("/")[0]
        if major in ("image", "video", "audio"):
            return major
        if mime == "application/pdf":
            return "pdf"
        if "wordprocessingml" in mime or mime == "application/msword":
            return "word"
        if "spreadsheetml" in mime or mime == "application/vnd.ms-excel":
            return "excel"
        if "presentationml" in mime or mime == "application/vnd.ms-powerpoint":
            return "powerpoint"
        if mime in ("application/zip", "application/x-7z-compressed", "application/vnd.rar", "application/gzip", "application/x-tar"):
            return "archive"
        if mime in ("application/json", "application/xml", "application/javascript", "text/html", "text/css", "text/x-python"):
            return "code"
        if major == "text":
            return "text"
        return "other"

    def has_thumbnail(self, url, kind: str) -> bool:
        """Whether the file's host and type are ones that have thumbnails; decided from the data already at hand (no call per file)."""
        return kind in self.THUMBNAIL_KINDS and self.is_share_url(url)

    def image_type(self, head: bytes) -> str | None:
        """JPEG, PNG or WEBP from the magic bytes; anything else is None."""
        if head.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if head.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
            return "image/webp"
        return None

    def safe_graph_id(self, value) -> bool:
        return isinstance(value, str) and bool(self.GRAPH_ID.fullmatch(value)) and ".." not in value and value != "."

    def _resolve(self, note, broker, url: str) -> tuple[str, str] | None:
        """(drive id, item id) of the file behind a share URL, cached for an hour; None when it is gone, a folder or unreadable."""
        cache = AccountCache.for_broker(broker)
        key = ("share_item", url)
        marker = object()
        hit = cache.get(key, marker)
        if hit is not marker:
            return hit
        try:
            item = note.get(GraphPaths.drive_item_path(url, "id,parentReference,file,size,webUrl"))
        except GraphError as ex:
            if ex.status in (400, 403, 404):
                cache.set(key, None, self.ITEM_TTL)
                return None
            raise
        drive = ((item or {}).get("parentReference") or {}).get("driveId")
        item_id = (item or {}).get("id")
        found = (drive, item_id) if (item or {}).get("file") is not None and self.safe_graph_id(drive) and self.safe_graph_id(item_id) else None
        cache.set(key, found, self.ITEM_TTL)
        return found

    def _content(self, note, path: str) -> bytes | None:
        try:
            data = note.get(path, raw="bytes")
        except GraphError as ex:
            if ex.status in (400, 404, 415):
                return None
            raise
        if not data or len(data) > self.MAX_THUMBNAIL_BYTES or self.image_type(data[:12]) is None:
            return None
        return data

    def chat_file_thumbnail(self, note, broker, url: str, size: str) -> bytes | None:
        """The thumbnail bytes of a chat-shared file, or None when the URL isn't a share link or the file has no thumbnail."""
        if size not in self.SIZES or not self.is_share_url(url):
            return None
        ids = self._resolve(note, broker, url)
        if not ids:
            return None
        return self._content(note, f"drives/{quote(ids[0], safe='')}/items/{quote(ids[1], safe='')}/thumbnails/0/{size}/content")

    def drive_item_thumbnail(self, note, item_id: str, size: str, drive_id: str | None = None) -> bytes | None:
        """The thumbnail of an item in the user's OneDrive, or of `drive_id`'s item (a team library, a shared drive)."""
        if size not in self.SIZES or not self.safe_graph_id(item_id) or (drive_id is not None and not self.safe_graph_id(drive_id)):
            return None
        base = f"drives/{quote(drive_id, safe='')}/items" if drive_id else "me/drive/items"
        return self._content(note, f"{base}/{quote(item_id, safe='')}/thumbnails/0/{size}/content")
