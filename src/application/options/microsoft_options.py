import os
from dataclasses import dataclass


@dataclass
class MicrosoftOptions:
    """Reaching Microsoft 365 through the FOCI first-party clients.

    No app registration: the device-code sign-in runs against Microsoft's own Office client, which supports the device flow and issues a
    FOCI family refresh token that OutNote's broker trades for whatever first-party client each Graph call needs. That client never handles a password.
    """

    device_client_id: str
    tenant: str
    graph_default: str = "https://graph.microsoft.com/.default"
    device_grant: str = "urn:ietf:params:oauth:grant-type:device_code"

    @classmethod
    def from_environment(cls) -> "MicrosoftOptions":
        return cls(device_client_id=os.getenv("MS_DEVICE_CLIENT_ID", "d3590ed6-52b3-4102-aeff-aad2292ab01c"), tenant=os.getenv("MS_TENANT", "common"))

    @property
    def device_scope(self) -> str:
        return f"{self.graph_default} offline_access openid profile"

    @property
    def devicecode_url(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant}/oauth2/v2.0/devicecode"

    @property
    def token_url(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant}/oauth2/v2.0/token"
