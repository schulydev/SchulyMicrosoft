import re


class ByteRange:
    """The one kind of `Range` a media player needs: `bytes=start-` or `bytes=start-end`. Anything else reads as no range, which HTTP allows."""

    PATTERN = re.compile(r"bytes=(\d{1,15})-(\d{0,15})")
    CONTENT_RANGE = re.compile(r"bytes (\d{1,15}-\d{1,15}|\*)/(\d{1,15}|\*)")

    @classmethod
    def parse(cls, value: str | None) -> str | None:
        match = cls.PATTERN.fullmatch(value.strip()) if isinstance(value, str) else None
        if match is None or (match[2] and int(match[2]) < int(match[1])):
            return None
        return match[0]

    @classmethod
    def total(cls, content_range: str | None) -> int | None:
        """The whole file's size in a `Content-Range`, or None when it is unknown."""
        match = cls.CONTENT_RANGE.fullmatch(content_range or "")
        return int(match[2]) if match and match[2] != "*" else None

    @classmethod
    def safe_content_range(cls, content_range: str | None) -> str | None:
        return content_range if content_range and cls.CONTENT_RANGE.fullmatch(content_range) else None
