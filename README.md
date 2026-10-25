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

The student signs in **once** with the OAuth 2.0 **device-code flow**: the service returns a
short code and a URL, the student opens the URL on Microsoft's real sign-in page (so push,
number-matching and passkeys all work) and enters the code. No password ever reaches this
service. The result is a FOCI family refresh token that the **caller stores** and sends back
on each read; the broker rotates it and the service hands the new one back in the
`X-MS-Refresh-Token` header. **The service stores nothing.**

```
POST /api/auth/device/start          → { user_code, verification_uri, device_code, ... }
POST /api/auth/device/poll           { device_code } → pending | complete (+ refresh_token, account)
GET  /api/me                         header X-MS-Refresh-Token
GET  /api/mail?folder=&top=&unread=  "
GET  /api/calendar?top=              "
GET  /api/files?path=&top=           "
GET  /api/chats?top=                 "
GET  /api/notebooks                  "
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
