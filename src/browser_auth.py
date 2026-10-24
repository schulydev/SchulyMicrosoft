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

from src import config, outnote_client

# OfficeHome: pre-consented, issues a FOCI family refresh token. Public client id.
OFFICEHOME_CLIENT_ID = "4765445b-32c6-49b0-83e6-1d93765276ca"
# Microsoft's documented native-client redirect — the code lands here in the URL; nothing is hosted.
NATIVE_REDIRECT = "https://login.microsoftonline.com/common/oauth2/nativeclient"
AUTHORIZE_URL = f"https://login.microsoftonline.com/{config.TENANT}/oauth2/v2.0/authorize"
SCOPE = f"{config.GRAPH_DEFAULT} offline_access openid profile"


def build_authorize_url() -> tuple[str, str]:
    """The Microsoft authorize URL for the WebView, and the PKCE code_verifier the caller keeps."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    url = AUTHORIZE_URL + "?" + urlencode({
        "client_id": OFFICEHOME_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": NATIVE_REDIRECT,
        "response_mode": "query",
        "scope": SCOPE,
        "state": secrets.token_urlsafe(16),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    return url, verifier


async def exchange_code(code: str, code_verifier: str, client: httpx.AsyncClient | None = None) -> dict:
    """Redeem the authorization code from the redirect for tokens."""
    return await outnote_client._post(config.TOKEN_URL, {
        "grant_type": "authorization_code",
        "client_id": OFFICEHOME_CLIENT_ID,
        "code": code,
        "redirect_uri": NATIVE_REDIRECT,
        "code_verifier": code_verifier,
    }, client)
