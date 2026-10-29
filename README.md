<h1 align="center">SchulyMicrosoft</h1>

<p align="center">
  <strong>Stateless Microsoft 365 access for Schuly, over <a href="https://github.com/PianoNic/OutNote">OutNote</a> / <a href="https://github.com/PianoNic/Entrance">Entrance</a>.</strong>
</p>

---

The Schuly **Microsoft plugin** calls this service to read a student's own Microsoft 365
data — mail, calendar, OneDrive, OneNote, Teams chats — without registering an Azure app or
asking a tenant admin for consent. It rides Microsoft's own pre-consented first-party
clients through OutNote's FOCI token broker.

## How sign-in works

The student signs in **once**, always on Microsoft's real sign-in page (so push,
number-matching and passkeys all work). The one exception is the password sign-in route below (see
"Password sign-in"); every other route never sees a password. Two flows:

- **Browser sign-in** (what the Schuly Microsoft plugin uses): an OAuth 2.0
  authorization-code + PKCE flow. `browser/start` returns the authorize URL and a
  `code_verifier`; the app opens the URL in a WebView, captures the `?code=` from the
  redirect to Microsoft's native-client URL, and sends it back with the verifier to
  `browser/complete`. Works on tenants that block the device-code flow.
- **Device-code flow**: the service returns a short code and a URL, the student opens the
  URL and enters the code, and the caller polls until it completes.

### Password sign-in

For the Schuly web app, which cannot host Microsoft's page: `password/start` receives the Microsoft
password **once**, passes it to Entrance on a worker thread and drops it. It is held only in memory for
that call and is never stored, cached, logged or returned. If Microsoft asks for MFA the sign-in pauses
and `start` returns the methods the account offers (`push` = Authenticator number matching, `otp` = a
code from an authenticator app); `method` picks one (and may switch mid-way), `otp` submits the code.
No MFA means `start` completes right away. Federated/ADFS accounts, unsupported methods and
Conditional Access blocks return `error` with code `unsupported` / `blocked`.
These routes are callable only by the Schuly plugin: every request needs the shared secret in
`X-Schuly-Service-Key` (must equal the `SCHULY_SERVICE_KEY` env var; if that is unset the routes answer 503)
and the signed-in Schuly user's id in `X-Schuly-User-Id` (else 401). A job belongs to that user: anyone else gets
404 for it. Only failed password attempts count against the per-(user, account) limit, and authenticator
codes are budgeted (5 per job, 10 per hour per user and account; then `error` / `otp_exhausted`). Sign-in jobs live in
memory for at most 10 minutes, so **run exactly one process** (`asgi.py` pins `workers=1`).

Either way the result is a FOCI family refresh token that the **caller stores** and sends
back on each read; the broker rotates it and the service hands the new one back in the
`X-MS-Refresh-Token` header. **The service stores nothing.**

```
POST /api/auth/browser/start         → { authorize_url, redirect_uri, code_verifier }
POST /api/auth/browser/complete      { code, code_verifier } → complete (+ refresh_token, account) | error
POST /api/auth/device/start          → { user_code, verification_uri, device_code, ... }
POST /api/auth/device/poll           { device_code } → pending | complete (+ refresh_token, account)
POST /api/auth/password/start        { username, password } → complete | mfa_required { methods } | error { code }
POST /api/auth/password/{id}/method  { method: push|otp } → push_pending { number, expires_in } | otp_required
POST /api/auth/password/{id}/otp     { code } → complete | otp_invalid { attempts_left } | error
GET  /api/auth/password/{id}         → current status (push_pending | complete | denied | timed_out | error | ...)
DELETE /api/auth/password/{id}       → 204 (cancel)
GET  /api/me                         header X-MS-Refresh-Token
GET  /api/mail?folder=&top=&skip=&unread=&search=  "  (skip pages, not with search; folder: well-known name or folder id)
GET  /api/mail/folders               "  (nested: childFolders[])
GET  /api/mail/{id}                  "  (full message incl. body)
GET  /api/mail/{id}/attachments      "  (metadata only)
GET  /api/mail/{id}/attachments/{aid} "  (bytes, <= 25 MB, no-store)
POST /api/mail/send                  { to[], cc?, bcc?, subject, body, html?, attachments?[{name,contentType,contentBase64}] } → 204
POST /api/mail/drafts                same body → created draft (201)
POST /api/mail/drafts/{id}/send      → 204
POST /api/mail/{id}/reply            { comment, replyAll? } → 204
POST /api/mail/{id}/forward          { to[], comment? } → 204
POST /api/mail/{id}/read             { read }
POST /api/mail/{id}/flag             { status: flagged|complete|notFlagged }
POST /api/mail/{id}/move             { folder } → moved message
DELETE /api/mail/{id}                → 204
GET  /api/calendar?top=&start=&end=  "
GET  /api/files?path=&top=           "
GET  /api/chats?top=                 "
GET  /api/notebooks                  "
GET  /api/chats/{id}/messages?top=   "  (newest first, top <= 50)
POST /api/chats/{id}/messages        { text } (1-4000 chars) → created message
POST /api/chats/{id}/read            → 204
GET  /api/users/{id}/photo?size=     "  (48|64|96|120|240) → image bytes, 404 if none
GET  /api/chats/{id}/messages/{mid}/files/{fid}/thumbnail?size=  small|medium|large → JPEG/PNG/WEBP, 404 if none
GET  /api/files/{itemId}/thumbnail?size=                          "  (OneDrive item)
GET  /api/emojis/catalogue?locale=  Teams emoji catalogue (no token, cached 24 h)
GET  /api/emojis/custom/{documentId}?animated=  tenant custom emoji image (message emojis[].documentId)
```

## Run

```sh
pip install -r requirements.txt
python asgi.py                 # http://localhost:8010  (Swagger at /docs)
```

```sh
docker build -t schulymicrosoft .
docker run -p 8010:8010 schulymicrosoft
```

## Disclaimer

For **educational and research purposes**, and only against **accounts you own**. It drives a
real Microsoft sign-in; treat any returned refresh token like a password. Reusing Microsoft's
first-party clients is not an officially supported integration path, and a tenant may block
it. Not affiliated with or endorsed by Microsoft. See [OutNote](https://github.com/PianoNic/OutNote)
and [Entrance](https://github.com/PianoNic/Entrance) for the auth mechanics.

## License

PolyForm Noncommercial License 1.0.0
