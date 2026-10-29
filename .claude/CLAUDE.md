# CLAUDE.md — SchulyMicrosoft

Stateless FastAPI service giving Schuly access to a student's own Microsoft 365 data via
[OutNote](https://github.com/PianoNic/OutNote) (built on [Entrance](https://github.com/PianoNic/Entrance)).
The Schuly **Microsoft plugin** is the only caller.

## What it is / isn't

- **Stateless.** No database, no stored tokens. The caller owns the FOCI refresh token and
  sends it back in the `X-MS-Refresh-Token` header; reads return the rotated token in the
  same response header.
- Sign-in is the **browser sign-in** (authorization code + PKCE in a WebView, used by the
  plugin) or the **device-code flow** — the student always authenticates on Microsoft's real
  page. This service never sees a password. Do **not** add password/credential endpoints.
- Uses only the **public** OutNote/Entrance API (`outnote.OutNote`, `entrance.Broker`,
  `entrance.http_client`) plus the documented OAuth calls for the browser and device flows. Don't
  reach into their private modules. The one non-Graph surface is the Teams chat service for group
  chat pictures (`teams_chat.py`): a Teams-client token for `api.spaces.skype.com` is traded at
  `teams.microsoft.com/api/authsvc/v1.0/authz` for a skype token.

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
  outnote_client.py     # thin OutNote/Entrance wrapper (device start/poll, build_client)
  models.py             # pydantic DTOs
  account_cache.py      # per-account TTL cache living on the shared broker
  folder_roles.py       # well-known mail folder names via one $batch
  teams_chat.py         # group chat pictures over the Teams chat service (skype token, AMS)
  chat_read.py          # chat messages + media/files/cards for the web
  chat_html.py          # composer HTML allowlist sanitizer, body media/card extraction
  chat_send.py          # rich sends: hosted images, GIFs, mentions, OneDrive file shares
  people_photos.py      # profile photos by e-mail (mail senders), cached per account
  gifs.py               # Giphy search (needs GIPHY_API_KEY; 503 without)
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
