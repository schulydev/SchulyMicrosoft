"""Browser sign-in: standard OAuth 2.0 authorization-code + PKCE against the OfficeHome client.

This is the flow `outnote login` uses and works on tenants that block the device-code flow.
The app opens the authorize URL in a WebView on Microsoft's real sign-in page, waits for the
redirect to the native-client URL carrying `?code=`, and sends the code here to exchange for a
FOCI refresh token. The caller holds the `code_verifier` between the two calls; nothing is stored.
"""

import base64
import hashlib
import secrets
from urllib.parse import urlencode

import httpx

from src.application.abstractions.i_browser_sign_in import IBrowserSignIn
from src.application.abstractions.i_microsoft_http_clients import IMicrosoftHttpClients
from src.application.options.microsoft_options import MicrosoftOptions


class BrowserSignInClient(IBrowserSignIn):
    # OfficeHome: pre-consented, issues a FOCI family refresh token. Public client id.
    OFFICEHOME_CLIENT_ID = "4765445b-32c6-49b0-83e6-1d93765276ca"
    # Microsoft's documented native-client redirect — the code lands here in the URL; nothing is hosted.
    NATIVE_REDIRECT = "https://login.microsoftonline.com/common/oauth2/nativeclient"

    def __init__(self, http: IMicrosoftHttpClients, options: MicrosoftOptions):
        self._http = http
        self._options = options

    def build_authorize_url(self) -> tuple[str, str]:
        """The Microsoft authorize URL for the WebView, and the PKCE code_verifier the caller keeps."""
        verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        url = f"https://login.microsoftonline.com/{self._options.tenant}/oauth2/v2.0/authorize" + "?" + urlencode({
            "client_id": self.OFFICEHOME_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": self.NATIVE_REDIRECT,
            "response_mode": "query",
            "scope": f"{self._options.graph_default} offline_access openid profile",
            "state": secrets.token_urlsafe(16),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        })
        return url, verifier

    async def exchange_code(self, code: str, code_verifier: str, client: httpx.AsyncClient | None = None) -> dict:
        """Redeem the authorization code from the redirect for tokens."""
        return await self._http.post_form(self._options.token_url, {
            "grant_type": "authorization_code",
            "client_id": self.OFFICEHOME_CLIENT_ID,
            "code": code,
            "redirect_uri": self.NATIVE_REDIRECT,
            "code_verifier": code_verifier,
        }, client)
