from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.api.http_headers import HttpHeaders
from src.api.token_rotation.context_token_rotation import ContextTokenRotation


class TokenRotationMiddleware:
    """Puts the rotated refresh token recorded during a request on its response, whatever kind of response that turns out to be. Pure ASGI, so a stream is never buffered."""

    def __init__(self, app: ASGIApp, rotation: ContextTokenRotation):
        self._app = app
        self._rotation = rotation

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        slot = self._rotation.open_slot()

        async def send_with_token(message: Message) -> None:
            if message["type"] == "http.response.start" and slot.refresh_token:
                MutableHeaders(scope=message)[HttpHeaders.REFRESH_TOKEN_HEADER] = slot.refresh_token
            await send(message)

        await self._app(scope, receive, send_with_token)
