"""Constants for reaching Microsoft 365 through the FOCI first-party clients.

No app registration: the device-code sign-in runs against Microsoft's own Office
client, which supports the device flow and issues a FOCI family refresh token that
OutNote's broker trades for whatever first-party client each Graph call needs.
"""

import os

# Microsoft "Office" client: device-flow enabled and FOCI. The user signs in on
# Microsoft's real page, so this never handles a password.
DEVICE_CLIENT_ID = os.getenv("MS_DEVICE_CLIENT_ID", "d3590ed6-52b3-4102-aeff-aad2292ab01c")
TENANT = os.getenv("MS_TENANT", "common")

GRAPH_DEFAULT = "https://graph.microsoft.com/.default"
DEVICE_SCOPE = f"{GRAPH_DEFAULT} offline_access openid profile"

DEVICECODE_URL = f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/devicecode"
TOKEN_URL = f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"

REFRESH_TOKEN_HEADER = "X-MS-Refresh-Token"

# The password sign-in routes take a Microsoft password, so only the Schuly plugin may call them: it sends
# the shared secret (SCHULY_SERVICE_KEY) in SERVICE_KEY_HEADER and the signed-in Schuly user's id in USER_ID_HEADER.
# With SCHULY_SERVICE_KEY unset the routes answer 503 (never open).
SERVICE_KEY_ENV = "SCHULY_SERVICE_KEY"
SERVICE_KEY_HEADER = "X-Schuly-Service-Key"
USER_ID_HEADER = "X-Schuly-User-Id"
