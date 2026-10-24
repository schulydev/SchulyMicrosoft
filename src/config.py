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
