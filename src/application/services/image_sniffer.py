class ImageSniffer:
    """Image formats from the magic bytes."""

    CHAT_IMAGE_TYPES = {b"\x89PNG": "image/png", b"\xff\xd8\xff": "image/jpeg", b"GIF8": "image/gif"}

    @classmethod
    def chat_image(cls, head: bytes) -> str | None:
        """PNG, JPEG, GIF or WEBP from the magic bytes; anything else is None."""
        for magic, mime in cls.CHAT_IMAGE_TYPES.items():
            if head.startswith(magic):
                return mime
        if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
            return "image/webp"
        return None

    @staticmethod
    def photo(data: bytes) -> str:
        # OutNote's public getter returns only the body bytes, so sniff the format from the magic number.
        if data[1:4] == b"PNG":
            return "image/png"
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return "image/gif"
        return "image/jpeg"
