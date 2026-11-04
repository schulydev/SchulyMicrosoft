# CLAUDE.md — SchulyMicrosoft

Stateless FastAPI service giving Schuly access to a student's own Microsoft 365 data via
[OutNote](https://github.com/PianoNic/OutNote) (built on [Entrance](https://github.com/PianoNic/Entrance)).
The Schuly **Microsoft plugin** is the only caller.

## What it is / isn't

- **Stateless** apart from the short-lived in-memory password sign-in jobs. No database, no stored tokens. The caller owns the FOCI refresh token and
  sends it back in the `X-MS-Refresh-Token` header; reads return the rotated token in the
  same response header.
- Sign-in is the **browser sign-in** (authorization code + PKCE in a WebView, used by the
  plugin) or the **device-code flow** — the student authenticates on Microsoft's real page — plus
  one exception for the web app: `POST /api/auth/password/start` receives the Microsoft password
  once for the push/TOTP sign-in, holds it only in memory for that call, and never stores, caches,
  logs or returns it. Every other route still never sees a password. Do **not** add any other
  password/credential endpoints.
- Password sign-in jobs (`src/infrastructure/password_signin/`) are **in memory only** (TTL <= 10 min, sweeper,
  max concurrent jobs, per-client and per-account rate limits). They hold progress and the result,
  never the password, so the service **must run as ONE process** (`asgi.py` pins `workers=1`; do not
  add uvicorn/gunicorn workers or replicas). Keep the password out of logs, job objects, errors
  and responses (the 422 handler for `/api/auth/password*` strips the echoed input on purpose).
- Uses only the **public** OutNote/Entrance API (`outnote.OutNote`, `entrance.Broker`,
  `entrance.http_client`) plus the documented OAuth calls for the browser and device flows. Don't
  reach into their private modules. Needs Python 3.11 or newer. The one non-Graph surface is the Teams chat service for group
  chat pictures (`TeamsChatClient`): a Teams-client token for `api.spaces.skype.com` is traded at
  `teams.microsoft.com/api/authsvc/v1.0/authz` for a skype token.

## OutNote / Entrance 2.x

- `entrance.http_client()` offers only `request`, `post`, `head` and `close`, takes a float timeout
  and reads every body into memory. Anything that must stay capped or be streamed uses
  `IMicrosoftHttpClients.download_client()` (httpx, HTTP/1.1, no redirects by default, no cookies kept,
  because all accounts share it). `open_download` opens a pre-authorized link before the answer starts, so a refusal is a real status; it follows
  redirects only through the host check, passes `Range` on and streams raw. `FileDownloads` keeps a link for 10 minutes, so a video's seeks cost no Graph calls. Don't call `note.download` or `note.download_shared`: they hold the
  whole file with no cap and no host check.
- `except entrance.HTTPError` works alone, but it is a tuple: unpack it next to other types.
- `TeamsFiles.download_url` stays: it serves the `shares/...` path chat files need, which OutNote's
  `download_url` can't. A folder is a 404 that says so; Graph's refusal at `/content` keeps its own
  status (403, 404, 415, 429).
- One `OutNote` per account lives on its broker. A throttled call raises `GraphError` 429 after about
  60 s, or at once with `retry=False`, which `AccountRunner` answers as 429 with `Retry-After` (and any rotated token) and logs as a warning with the masked route (`GraphCallTrail`). Keep ids and content out of that line. The chat file, thumbnail and message reads use `retry=False`: the caller waits, not a worker thread.
- Graph throttles the single chat message read (`chats/{id}/messages/{id}`) far sooner than the list, so `ChatReader.file_ref` answers from what the list already said, then asks `note.chat_message` (Teams' own API, which falls back to that same read and may answer 429 for it), and when that refuses or lacks the file, the list.
- `AccountRunner` strips `_native` from every result. No route calls OutNote's native reads today: chat
  messages stay on Graph's list because `ChatReader` and the callers need its attachments, mentions and
  reactions. `emails()` gets an explicit `$select` because the web's list shows `toRecipients`.
- Never add `SQLiteCache` or any other on-disk cache. `stream()` cursors would have to live in the plugin.

## Cold start

- Read `/me` only through `IProfileReader.get`: it asks `/me` once without OutNote's retries (Graph 429s it with ~21 s Retry-After) and falls back to the access token's claims (oid, name, upn).
- `GET /health/live` is always 200; `GET /health/ready` is 503 until the startup warm-up finished or 15 s passed
  (the Dockerfile `HEALTHCHECK` uses it).

## Code formatting

**Declaration signatures go on one line** — don't wrap a function/method parameter list
across multiple lines, however long. Call sites, comprehensions and multi-line `if`/`for`
stay as they are.

## Architecture

Onion clean architecture with CQRS through [mediatorx](https://pypi.org/project/mediatorx/), in SchulwareAPI's style and with SchulyServer's ideas.
**Dependencies only point inward**; `tests/test_architecture.py` parses every import under `src/` and fails when a file breaks this.

- `domain`: pure types, errors and validators. Imports nothing from the other rings and no framework.
- `application`: commands, queries, DTOs, options, services, and the ABCs it needs from outside (`abstractions/`). Imports only `domain` (plus `mediatorx` and `pydantic`), never FastAPI, OutNote, Entrance or httpx.
- `infrastructure`: implements those ABCs over OutNote, Entrance, Graph, Teams, Giphy and the file libraries. Never imports `api`.
- `api`: controllers, middleware and the composition root. Only `src/api/extensions/` may name concrete infrastructure classes.

Conventions:

- **Controllers are thin**: `@controller(router)` classes with `mediator: Mediator = Depends(get_mediator)` that translate HTTP and call `self.mediator.send(...)`. Route method names are the operation ids, so keep them; `OpenApiExtensions` strips the class name the decorator adds.
- **A command or query** is a dataclass paired with its handler in one file, one file per operation. A refresh token field is `field(repr=False)`, and so is anything else secret.
- **Constructor injection only**: nothing is reached through a module-level singleton. `ServiceCollection` holds the lifetimes (`add_singleton`, `add_scoped`, `add_handler`), one `<Area>Extensions` class per area, called from `Program` in `src/api/app.py`. Handlers are scoped; everything with state is a singleton: `JobStore`, `OutNoteClientFactory` (the per-account broker cache), `MicrosoftHttpClients`, `EmojiCatalogue`, `GifSearch`, `WarmUpTracker`.
- **Refusals**: raise `ServiceError(status, detail, headers)` or a subclass from anywhere; `ExceptionHandlingExtensions` is the one place that makes a response from it. `SignInRefused` is the password routes' shape, and they alone get the stripped 422.
- **Token rotation**: `AccountRunner` records the rotated token through `ITokenRotation`; `TokenRotationMiddleware` puts it on the response. It records on success, on a `ServiceError` raised by the action and on a 429, and not on a plain 401, 404 or 502. mediatorx has pipeline behaviors, but a behavior can't see the broker.

To add a route: a query or command with its handler in `src/application/`, its registration in the area's `src/api/extensions/<area>_extensions.py`, and a method on `src/api/controllers/<area>_controller.py`. A streaming answer returns a `FileStream` and the controller answers `FileResponses.stream(...)`.

## Layout

```
asgi.py                       # entrypoint (uvicorn on :8010)
src/
  api/
    app.py                    # Program: the composition root and the request pipeline
    controller.py             # class-based controller decorator (vendored, MIT, from SchulwareAPI)
    dependencies.py           # get_mediator, the password routes' service key and user id gate
    http_headers.py           # header names
    controllers/              # one @controller class per area
    extensions/               # <Area>Extensions (registration per area), exception handling, OpenAPI names
    di/                       # ServiceCollection, ServiceProvider (mediatorx's resolver)
    middleware/               # TokenRotationMiddleware
    token_rotation/           # ContextTokenRotation: the per-request slot behind ITokenRotation
    request_bodies/           # capped raw upload body, chat send body (JSON or multipart)
    responses/                # FileResponses: download, stream, inline PDF and image headers
  application/
    abstractions/             # I*: what the application needs from outside
    commands/ queries/        # one dataclass + handler per operation
    dtos/                     # pydantic request and response models, one per file
    options/                  # MicrosoftOptions, ServiceAuthOptions, PasswordSignInOptions, GiphyOptions, EmojiOptions
    services/                 # ChatHtmlSanitizer, OneNoteHtmlSanitizer, MailMessageBuilder, DriveFileTextReader, PasswordSignInResponder, ApplicationLifetime, WarmUpTracker, ...
  domain/
    errors/                   # ServiceError and its subclasses, SignInRefused, RateLimited, ...
    validation/               # GraphIds (the one id validator), RefreshTokenFormat
    files/ chat/ sign_in/     # limits, file results, outgoing message, emoji catalogue, sign-in states
  infrastructure/
    logging_config.py         # logger names
    microsoft/                # AccountRunner, OutNoteClientFactory, BrokerCache, SharedBroker, AccountCache, MicrosoftHttpClients, DeviceLoginClient, BrowserSignInClient, ProfileReader
    graph/                    # TeamsFiles, GraphSearch, OneNoteClient, OneNoteRunner, PdfConverter, FileThumbnails, ChannelMessages, PeoplePhotos, MailFolderRoles
    teams/                    # TeamsChatClient (skype token, AMS), ChatReader, ChatSender, ChatPresence, EmojiCatalogue
    giphy/                    # GifSearch (Teams' own GIF command with the account's sign-in; 503 when Teams refuses)
    files/                    # FileTextExtractor (lazy imports, zip-bomb guard, caps, paging)
    password_signin/          # JobStore, SignInJob (worker thread per job, MfaPrompt bridge), RateLimiter
tests/                        # pytest, fully mocked (no network); services.py resolves the singletons the tests patch
```

## Run / test

```sh
python asgi.py                       # http://localhost:8010  (/docs)
python -m pytest tests -q            # all mocked, no Microsoft calls
```

A real local check uses a refresh token from `outnote login` (`.ms_frt`); pass it as the
`X-MS-Refresh-Token` header. Never commit a token (`.gitignore` covers `.ms_frt`/`*.frt`).

## Versioning / release (KRINT)

`application.properties` (`APP_VERSION=x.y.z`, flat form, like SchulwareAPI) is the source of
truth. Releasing: `gh release create vX.Y.Z` → `release.yml` syncs the property and builds the
multi-arch image to `ghcr.io/schulydev/schulymicrosoft` (+ Docker Hub if the org secrets are
set). `release-drafter` drafts from labeled PRs; `version-bump` is a manual bump.

## Workflow (enforced, KRINT)

Issue (labeled) → branch `feature/<#>_PascalCase` → PR (labeled, body = Summary + `Closes #<n>`)
→ squash-merge + delete branch. Past-tense commit subjects. **No AI/Claude attribution anywhere.**

## Legal

Reusing Microsoft first-party clients + FOCI is a gray area (see the org-wide legal notes):
keep this out of app-store builds unless Centerboard/Microsoft terms are cleared. Account
owner's own data only.
