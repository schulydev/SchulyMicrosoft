<h1 align="center">SchulyMicrosoft</h1>

<p align="center">
  <strong>Stateless Microsoft 365 access for Schuly, over <a href="https://github.com/PianoNic/OutNote">OutNote</a> / <a href="https://github.com/PianoNic/Entrance">Entrance</a>.</strong>
</p>

> [!WARNING]
> **For educational and research purposes**, and only against **accounts you own**. It drives a real Microsoft sign-in, so treat any returned refresh token like a password. Reusing Microsoft's first-party clients isn't an officially supported integration path, and a tenant may block it. Not affiliated with or endorsed by Microsoft.

---

## What is SchulyMicrosoft?

Reading a mailbox over Graph normally takes a registered Azure app and admin consent, which a locked-down school tenant refuses. This service goes through Microsoft's own pre-consented first-party clients instead, so a student reaches their own mail, calendar, OneDrive, OneNote and Teams with neither.

The [Schuly Microsoft plugin](https://github.com/schulydev/SchulyPlugins/tree/main/src/Schuly.Plugin.Microsoft) is its only caller.

## How sign-in works

The student signs in once. The mobile app uses Microsoft's real page in a WebView, other callers can use a device code, and the web app, which can't host that page, sends the password once. That password stays in memory for the one call and is never stored or logged.

Each way ends in a refresh token that the **caller stores** and sends back in `X-MS-Refresh-Token`. The rotated token comes back in the same header. **The service stores nothing.**

Every route is listed at `/docs` on a running service, and [the docs](https://docs.schuly.dev/SchulyMicrosoft/) cover the flows. When Microsoft keeps throttling a call, the service waits about 60 seconds, then answers `429` with `Retry-After`.

## Run

Needs Python 3.11 or newer. The Docker image uses 3.13.

```sh
pip install -r requirements.txt
python asgi.py                 # http://localhost:8010
```

```sh
docker build -t schulymicrosoft .
docker run -p 8010:8010 schulymicrosoft
```

Password sign-in answers `503` until you set `SCHULY_SERVICE_KEY`. Sign-in jobs live in memory, so run exactly one process.

The code is an onion in `src/`: `domain`, `application`, then `infrastructure` and `api`. `tests/test_architecture.py` fails if a dependency points outward.

## License

[PolyForm Noncommercial 1.0.0](LICENSE)
