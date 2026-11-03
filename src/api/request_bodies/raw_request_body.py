from fastapi import Request

from src.api.request_bodies.limited_request import LimitedRequest
from src.application.abstractions.i_request_body import IRequestBody


class RawRequestBody(IRequestBody):
    """An upload's raw bytes."""

    def __init__(self, request: Request):
        self._request = request

    @property
    def declared_length(self) -> str | None:
        return self._request.headers.get("content-length")

    async def read(self, cap: int) -> bytes:
        body = bytearray()
        async for chunk in LimitedRequest.limit(self._request, cap).stream():
            body.extend(chunk)
        data = bytes(body)
        del body
        return data
