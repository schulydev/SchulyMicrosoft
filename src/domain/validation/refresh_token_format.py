import re

from src.domain.errors.service_error import ServiceError


class RefreshTokenFormat:
    """The shape a caller's refresh token must have before it is used at all."""

    TOKEN_PATTERN = re.compile(r"[\x21-\x7e]{4,16384}")  # printable ASCII, no whitespace

    @classmethod
    def check(cls, token: str) -> None:
        if not cls.TOKEN_PATTERN.fullmatch(token):
            raise ServiceError(401, "Missing or malformed Microsoft token.")
