import posixpath
import re


class ContentNames:
    """File names and content types of untrusted files, made safe to serve."""

    CONTENT_TYPE_PATTERN = re.compile(r"[A-Za-z0-9][\w.+-]{0,126}/[A-Za-z0-9][\w.+-]{0,126}")
    ACTIVE_TYPE_PARTS = ("html", "svg", "xml", "javascript", "ecmascript", "multipart")
    GENERIC_TYPES = ("", "application/octet-stream", "binary/octet-stream", "application/binary")
    TYPES_BY_EXTENSION = {
        "mp4": "video/mp4", "m4v": "video/mp4", "webm": "video/webm", "mov": "video/quicktime", "ogv": "video/ogg",
        "mp3": "audio/mpeg", "m4a": "audio/mp4", "wav": "audio/wav", "ogg": "audio/ogg", "oga": "audio/ogg", "opus": "audio/ogg", "flac": "audio/flac", "aac": "audio/aac",
        "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp", "avif": "image/avif", "heic": "image/heic",
        "pdf": "application/pdf",
    }

    @classmethod
    def safe_content_type(cls, value: str | None) -> str:
        # Attachments are untrusted: anything that could run as a page or script is served as opaque bytes.
        content_type = (value or "").split(";")[0].strip().lower()
        if not cls.CONTENT_TYPE_PATTERN.fullmatch(content_type) or any(part in content_type for part in cls.ACTIVE_TYPE_PARTS):
            return "application/octet-stream"
        return content_type

    @classmethod
    def media_type(cls, name: str | None, mime: str | None) -> str:
        """What to serve a file as: Graph's type, or from the extension when Graph leaves it out or calls it generic. An active type stays opaque, and the map holds none."""
        if (mime or "").split(";")[0].strip().lower() not in cls.GENERIC_TYPES:
            return cls.safe_content_type(mime)
        extension = posixpath.splitext(name or "")[1].lstrip(".").lower()
        return cls.TYPES_BY_EXTENSION.get(extension, "application/octet-stream")

    @staticmethod
    def safe_name(name: str | None) -> str:
        cleaned = re.sub(r'[\x00-\x1f\x7f\\/:*?"<>|]', "_", name or "")
        return cleaned.strip(" .")[:255] or "attachment"
