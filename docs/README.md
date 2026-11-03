# SchulyMicrosoft documentation

SchulyMicrosoft is a stateless FastAPI service that gives Schuly access to a student's own Microsoft
365 data: mail, calendar, OneDrive, OneNote, and Teams. The Schuly Microsoft plugin is its only caller.

It needs no Azure app and no tenant admin consent, because it uses Microsoft's own pre-consented
clients through [OutNote](https://github.com/PianoNic/OutNote) and
[Entrance](https://github.com/PianoNic/Entrance).

- [Development setup](setup/development.md)
- [API routes](https://github.com/schulydev/SchulyMicrosoft#how-sign-in-works), also available at `/docs` on a running service

## How sign-in works

The result of every sign-in is a refresh token. The caller stores it and sends it with each read in
the `X-MS-Refresh-Token` header. The service returns the rotated token in the same header and stores
nothing.

| Flow | Used by | How it works |
|---|---|---|
| Browser sign-in | The plugin in the mobile app | Authorization code with PKCE on Microsoft's own page in a WebView |
| Device code | Other callers | The student enters a short code on Microsoft's page while the caller polls |
| Password sign-in | The web app, which can't host Microsoft's page | The service receives the password once, for that call |

### Password sign-in

The service holds the password in memory for that call only, and never stores, caches, logs, or
returns it. If Microsoft asks for MFA, the sign-in pauses and offers `push` or `otp`.

Only the Schuly plugin can call these routes:

- Every request needs the shared secret in `X-Schuly-Service-Key`. It must equal `SCHULY_SERVICE_KEY`. If that variable isn't set, the routes answer 503.
- Every request needs the Schuly user's id in `X-Schuly-User-Id`. A sign-in job belongs to that user.

Sign-in jobs live in memory for up to 10 minutes, so the service must run as exactly one process.
`asgi.py` sets `workers=1`.

## Disclaimer

For educational and research purposes, and only against accounts you own. The service drives a real
Microsoft sign-in, so treat any returned refresh token like a password. Reusing Microsoft's
first-party clients isn't an officially supported integration path, and a tenant may block it. The
project isn't affiliated with or endorsed by Microsoft.
