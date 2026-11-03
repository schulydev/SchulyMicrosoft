import httpx

from src.application.abstractions.i_device_login import IDeviceLogin
from src.application.abstractions.i_microsoft_http_clients import IMicrosoftHttpClients
from src.application.options.microsoft_options import MicrosoftOptions
from src.domain.errors.microsoft_error import MicrosoftError


class DeviceLoginClient(IDeviceLogin):
    """The device-code sign-in. Nothing here is stored server-side."""

    def __init__(self, http: IMicrosoftHttpClients, options: MicrosoftOptions):
        self._http = http
        self._options = options

    async def start_device_login(self, client: httpx.AsyncClient | None = None) -> dict:
        """Begin the device-code flow: returns user_code, verification_uri and the device_code to poll with."""
        data = await self._http.post_form(self._options.devicecode_url, {"client_id": self._options.device_client_id, "scope": self._options.device_scope}, client)
        if not data.get("device_code"):
            raise MicrosoftError(data.get("error", "no_device_code"), data.get("error_description", "the client may not support the device flow"))
        return data

    async def poll_device_login(self, device_code: str, client: httpx.AsyncClient | None = None) -> dict:
        """Poll once. Returns the raw token response: access_token + refresh_token, or error=authorization_pending."""
        return await self._http.post_form(self._options.token_url, {"grant_type": self._options.device_grant, "client_id": self._options.device_client_id, "device_code": device_code}, client)
