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
number-matching and passkeys all work). No password ever reaches this service. Two flows:

- **Browser sign-in** (what the Schuly Microsoft plugin uses): an OAuth 2.0
  authorization-code + PKCE flow. `browser/start` returns the authorize URL and a
  `code_verifier`; the app opens the URL in a WebView, captures the `?code=` from the
  redirect to Microsoft's native-client URL, and sends it back with the verifier to
  `browser/complete`. Works on tenants that block the device-code flow.
- **Device-code flow**: the service returns a short code and a URL, the student opens the
  URL and enters the code, and the caller polls until it completes.

Either way the result is a FOCI family refresh token that the **caller stores** and sends
back on each read; the broker rotates it and the service hands the new one back in the
`X-MS-Refresh-Token` header. **The service stores nothing.**

```
POST /api/auth/browser/start         → { authorize_url, redirect_uri, code_verifier }
POST /api/auth/browser/complete      { code, code_verifier } → complete (+ refresh_token, account) | error
POST /api/auth/device/start          → { user_code, verification_uri, device_code, ... }
POST /api/auth/device/poll           { device_code } → pending | complete (+ refresh_token, account)
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
