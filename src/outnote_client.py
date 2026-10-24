"""Thin, stateless wrapper over OutNote / Entrance.

The device-code sign-in is two documented OAuth calls (start + poll). Data reads
build an OutNote client from the caller's FOCI refresh token, which the broker may
rotate; callers get the rotated token back and own its persistence. Nothing here is
stored server-side.
"""

from collections.abc import Callable

import httpx
from entrance import Broker
from outnote import OutNote

from src import config


class MicrosoftError(Exception):
    def __init__(self, error: str, description: str = ""):
        self.error = error
        super().__init__(f"{error}: {description}" if description else error)


async def start_device_login(client: httpx.AsyncClient | None = None) -> dict:
    """Begin the device-code flow: returns user_code, verification_uri and the device_code to poll with."""
    data = await _post(config.DEVICECODE_URL, {"client_id": config.DEVICE_CLIENT_ID, "scope": config.DEVICE_SCOPE}, client)
    if not data.get("device_code"):
        raise MicrosoftError(data.get("error", "no_device_code"), data.get("error_description", "the client may not support the device flow"))
    return data


async def poll_device_login(device_code: str, client: httpx.AsyncClient | None = None) -> dict:
    """Poll once. Returns the raw token response: access_token + refresh_token, or error=authorization_pending."""
    return await _post(config.TOKEN_URL, {"grant_type": config.DEVICE_GRANT, "client_id": config.DEVICE_CLIENT_ID, "device_code": device_code}, client)


def build_client(refresh_token: str) -> tuple[OutNote, Broker]:
    """An OutNote client wired to a broker over the caller's refresh token; read `broker.refresh_token` after use for the rotated value."""
    broker = Broker(refresh_token)
    return OutNote(broker), broker


async def _post(url: str, data: dict, client: httpx.AsyncClient | None) -> dict:
    owned = client is None
    client = client or httpx.AsyncClient(timeout=30.0)
    try:
        response = await client.post(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
        return response.json()
    finally:
        if owned:
            await client.aclose()


# Read helpers, kept tiny so routers stay declarative. Each returns plain JSON-able data.
def read(outnote: OutNote, action: Callable[[OutNote], object]) -> object:
    return action(outnote)
