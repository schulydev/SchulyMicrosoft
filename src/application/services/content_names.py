import re


class ContentNames:
    """File names and content types of untrusted files, made safe to serve."""

    CONTENT_TYPE_PATTERN = re.compile(r"[A-Za-z0-9][\w.+-]{0,126}/[A-Za-z0-9][\w.+-]{0,126}")
    ACTIVE_TYPE_PARTS = ("html", "svg", "xml", "javascript", "ecmascript", "multipart")

    @classmethod
    def safe_content_type(cls, value: str | None) -> str:
        # Attachments are untrusted: anything that could run as a page or script is served as opaque bytes.
        content_type = (value or "").split(";")[0].strip().lower()
        if not cls.CONTENT_TYPE_PATTERN.fullmatch(content_type) or any(part in content_type for part in cls.ACTIVE_TYPE_PARTS):
            return "application/octet-stream"
        return content_type

    @staticmethod
    def safe_name(name: str | None) -> str:
        cleaned = re.sub(r'[\x00-\x1f\x7f\\/:*?"<>|]', "_", name or "")
        return cleaned.strip(" .")[:255] or "attachment"
