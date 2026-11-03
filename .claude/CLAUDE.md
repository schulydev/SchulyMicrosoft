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
- Password sign-in jobs (`src/password_signin.py`) are **in memory only** (TTL <= 10 min, sweeper,
  max concurrent jobs, per-client and per-account rate limits). They hold progress and the result,
  never the password, so the service **must run as ONE process** (`asgi.py` pins `workers=1`; do not
  add uvicorn/gunicorn workers or replicas). Keep the password out of logs, job objects, errors
  and responses (the 422 handler for `/api/auth/password*` strips the echoed input on purpose).
- Uses only the **public** OutNote/Entrance API (`outnote.OutNote`, `entrance.Broker`,
  `entrance.http_client`) plus the documented OAuth calls for the browser and device flows. Don't
  reach into their private modules. Needs Python 3.11 or newer. The one non-Graph surface is the Teams chat service for group
  chat pictures (`teams_chat.py`): a Teams-client token for `api.spaces.skype.com` is traded at
  `teams.microsoft.com/api/authsvc/v1.0/authz` for a skype token.

## OutNote / Entrance 2.x

- `entrance.http_client()` offers only `request`, `post`, `head` and `close`, takes a float timeout
  and reads every body into memory. Anything that must stay capped or be streamed uses
  `outnote_client.download_client()` (httpx, HTTP/1.1, no redirects by default, no cookies kept,
  because all accounts share it). Don't call `note.download` or `note.download_shared`: they hold the
  whole file with no cap and no host check.
- `except entrance.HTTPError` works alone, but it is a tuple: unpack it next to other types.
- `teams_files.download_url` stays: it serves the `shares/...` path chat files need, which OutNote's
  `download_url` can't. A folder is a 404 that says so; Graph's refusal at `/content` keeps its own
  status (403, 404, 415, 429).
- One `OutNote` per account lives on its broker. A throttled call raises `GraphError` 429 after about
  60 s, which `_read` answers as 429 with `Retry-After` (and any rotated token).
- `_read` strips `_native` from every result. No route calls OutNote's native reads today: chat
  messages stay on Graph's list because `chat_read` and the callers need its attachments, mentions and
  reactions. `emails()` gets an explicit `$select` because the web's list shows `toRecipients`.
- Never add `SQLiteCache` or any other on-disk cache. `stream()` cursors would have to live in the plugin.

## Cold start

- Read `/me` only through `profile.get`: it asks `/me` once without OutNote's retries (Graph 429s it with ~21 s Retry-After) and falls back to the access token's claims (oid, name, upn).
- `GET /health/live` is always 200; `GET /health/ready` is 503 until the startup warm-up finished or 15 s passed
  (the Dockerfile `HEALTHCHECK` uses it).

## Code formatting

**Declaration signatures go on one line** — don't wrap a function/method parameter list
across multiple lines, however long. Call sites, comprehensions and multi-line `if`/`for`
stay as they are.

## Layout

```
asgi.py                 # entrypoint (uvicorn on :8010)
src/
  app.py                # FastAPI app + routes
  config.py             # client ids, scopes, endpoints
  browser_auth.py       # browser sign-in (authorize URL + PKCE, code exchange)
  password_signin.py    # password sign-in jobs (worker thread per job, MfaPrompt bridge, rate limits)
  outnote_client.py     # thin OutNote/Entrance wrapper (device start/poll, build_client)
  models.py             # pydantic DTOs
  account_cache.py      # per-account TTL cache living on the shared broker
  profile.py            # the user's /me profile: one try, token claims on 429; cached 1 h (claims 5 min)
  folder_roles.py       # well-known mail folder names via one $batch
  teams_chat.py         # group chat pictures over the Teams chat service (skype token, AMS)
  chat_read.py          # chat messages + media/files/cards for the web
  chat_html.py          # composer HTML allowlist sanitizer, body media/card extraction
  chat_send.py          # rich sends: hosted images, GIFs, mentions, OneDrive file shares
  people_photos.py      # profile photos by e-mail (mail senders), cached per account
  emojis.py             # Teams emoji catalogue (public CDN, 24 h cache), message emoji parsing, send allowlist
  file_thumbs.py        # file kinds, SharePoint/OneDrive host check, chat file and drive thumbnails
  file_pdf.py           # Office files as PDF (Graph format=pdf); temp app-folder upload + delete + hourly sweep, converted-host allowlist
  teams_files.py        # joined teams, channels, team/channel library browsing (drive id via C_SITES), drive items, shared/recent files, download host check
  search.py             # Search API (files / mail / chats / channel posts) with hit locations, per-drive fallback, per-source errors; never logs the query
  file_text.py          # text out of docx/xlsx/pptx/pdf/text (lazy imports, zip-bomb guard, caps, paging)
  channel_messages.py   # Teams channel posts and replies, normalized (html to text)
  gifs.py               # Giphy search (needs GIPHY_API_KEY; 503 without)
  onenote.py            # OneNote over Graph: notebooks (own + teams), section tree, pages, search, writes, resource stream
  onenote_html.py       # OneNote page HTML allowlist sanitizer (read and write), text-box editability, InkML to SVG
tests/                  # pytest, fully mocked (no network)
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
