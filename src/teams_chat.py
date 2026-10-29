"""Group chat pictures from the Teams chat service.

Graph has no endpoint for a chat's custom picture, but the Teams clients read it from the chat
service: the conversation's `threadProperties.picture` holds `URL@<AMS object view URL>`, and the
image is served by AMS (the async media gateway). Both accept a skype token, which the Teams auth
service issues for a token to `api.spaces.skype.com`:

1. broker(Teams client, https://api.spaces.skype.com/.default) -> access token (FOCI redeem)
2. POST https://teams.microsoft.com/api/authsvc/v1.0/authz (Bearer) -> skypeToken, regionGtms.chatService
3. GET {chatService}/v1/users/ME/conversations/{chatId}?view=msnp24Equivalent (Authentication: skypetoken=...)
4. GET <picture URL> (Authorization: skype_token ...) -> image bytes

The skype token and each chat's picture URL are cached per account (see `account_cache`).
"""

import time
from concurrent.futures import ThreadPoolExecutor, wait
from urllib.parse import quote, urlsplit

import httpx
from entrance import TokenError, http_client

from src.account_cache import for_broker

TEAMS_CLIENT = "1fec8e78-bce4-4aaf-ab1b-5451cc387264"  # Microsoft Teams, a FOCI family client
SPACES_SCOPE = "https://api.spaces.skype.com/.default"
AUTHZ_URL = "https://teams.microsoft.com/api/authsvc/v1.0/authz"
# Picture URLs come from chat data any member can change, so only Microsoft's media hosts are fetched (the skype token rides on that request).
PICTURE_HOSTS = (".teams.microsoft.com", ".asm.skype.com")
PICTURE_TTL = 3600
SESSION_MARGIN = 120
SESSION_RETRY = 600  # after a refused sign-in to Teams, the list stops asking for a while
MAX_PICTURE_BYTES = 5 * 1024 * 1024
LOOKUP_WORKERS = 8
LOOKUP_BUDGET = 4.0  # seconds the chat list waits for uncached picture lookups
_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


class ChatServiceError(RuntimeError):
    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(f"Teams chat service {status}: {message}")


def _session(broker) -> tuple[str, str]:
    """(skype token, chat service base URL) for the account, minted once per token lifetime."""
    cache = for_broker(broker)
    hit = cache.get("teams_session")
    if hit:
        return hit
    with cache.lock("teams_session"):
        hit = cache.get("teams_session")
        if hit:
            return hit
        failed = cache.get("teams_session_failed")
        if failed:
            raise ChatServiceError(failed, "Teams sign-in refused recently")
        try:
            return _new_session(broker, cache)
        except ChatServiceError as ex:
            if ex.status in (401, 403):
                cache.set("teams_session_failed", ex.status, SESSION_RETRY)
            raise


def _new_session(broker, cache) -> tuple[str, str]:
    try:
        bearer = broker(TEAMS_CLIENT, SPACES_SCOPE)
    except TokenError as ex:
        if ex.error == "invalid_grant":
            raise
        # The tenant or client may not allow the Teams resource; that is a missing feature, not an expired sign-in.
        raise ChatServiceError(403, ex.error) from None
    r = http_client().post(AUTHZ_URL, headers={"Authorization": f"Bearer {bearer}"}, content=b"", timeout=_TIMEOUT)
    if r.status_code != 200:
        raise ChatServiceError(r.status_code, "authz refused")
    body = r.json()
    skype = (body.get("tokens") or {}).get("skypeToken")
    service = ((body.get("regionGtms") or {}).get("chatService") or "").rstrip("/")
    if not skype or not service.startswith("https://"):
        raise ChatServiceError(502, "authz returned no skype token or chat service")
    lifetime = int((body.get("tokens") or {}).get("expiresIn") or 3600)
    session = (skype, service)
    ams = _media_host((body.get("regionGtms") or {}).get("amsV2") or (body.get("regionGtms") or {}).get("ams"))
    cache.set("teams_ams", ams, max(60, lifetime - SESSION_MARGIN))
    cache.set("teams_session", session, max(60, lifetime - SESSION_MARGIN))
    return session


def _drop_session(broker):
    # A skype token the chat service no longer accepts; the next call mints a fresh one.
    for_broker(broker).set("teams_session", None, 0)


def _media_host(value) -> str | None:
    """The media service base URL when it is an https Microsoft media host, else None."""
    if not isinstance(value, str):
        return None
    parts = urlsplit(value)
    host = (parts.hostname or "").lower()
    return f"https://{host}" if parts.scheme == "https" and parts.port in (None, 443) and any(host.endswith(h) for h in PICTURE_HOSTS) else None


def _picture_url(value) -> str | None:
    if not isinstance(value, str) or not value.startswith("URL@"):
        return None
    url = value[4:]
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not any(host.endswith(h) for h in PICTURE_HOSTS):
        return None
    return url


def picture_url(broker, chat_id: str) -> str | None:
    """The chat's custom picture URL, or None when it has none (or the chat service doesn't know the chat)."""
    cache = for_broker(broker)
    key = ("chat_picture", chat_id)
    marker = object()
    hit = cache.get(key, marker)
    if hit is not marker:
        return hit
    skype, service = _session(broker)
    r = http_client().get(f"{service}/v1/users/ME/conversations/{quote(chat_id, safe='')}", params={"view": "msnp24Equivalent"}, headers={"Authentication": f"skypetoken={skype}"}, timeout=_TIMEOUT)
    if r.status_code == 404:
        url = None
    elif r.status_code != 200:
        if r.status_code == 401:
            _drop_session(broker)
        raise ChatServiceError(r.status_code, "conversation lookup failed")
    else:
        try:
            url = _picture_url((r.json().get("threadProperties") or {}).get("picture"))
        except (ValueError, AttributeError):
            url = None
    cache.set(key, url, PICTURE_TTL)
    return url


def picture(broker, chat_id: str) -> bytes | None:
    """The chat's custom picture bytes, or None when it has none. A skype token the service stopped accepting is replaced once."""
    try:
        return _download(broker, chat_id)
    except ChatServiceError as ex:
        if ex.status != 401:
            raise
    return _download(broker, chat_id)


def _download(broker, chat_id: str) -> bytes | None:
    url = picture_url(broker, chat_id)
    if not url:
        return None
    skype, _ = _session(broker)
    with http_client().stream("GET", url, headers={"Authorization": f"skype_token {skype}"}, timeout=_TIMEOUT, follow_redirects=False) as r:
        if r.status_code == 404:
            for_broker(broker).set(("chat_picture", chat_id), None, PICTURE_TTL)
            return None
        if r.status_code != 200:
            if r.status_code == 401:
                _drop_session(broker)
            raise ChatServiceError(r.status_code, "picture download failed")
        data = bytearray()
        for chunk in r.iter_bytes():
            data.extend(chunk)
            if len(data) > MAX_PICTURE_BYTES:
                raise ChatServiceError(413, "picture larger than 5 MB")
    return bytes(data)


def mark_images(broker, chats: list[dict], budget: float = LOOKUP_BUDGET) -> list[dict]:
    """Sets `hasImage` on each Graph chat. Only group chats can carry a custom picture; uncached ones are looked up in parallel within `budget` seconds, and a lookup that fails or runs late reads as False (it is cached once it lands)."""
    cache = for_broker(broker)
    found: dict[str, bool] = {}
    todo = []
    for chat in chats:
        cid = chat.get("id")
        if chat.get("chatType") != "group" or not isinstance(cid, str):
            found[cid] = False
            continue
        marker = object()
        hit = cache.get(("chat_picture", cid), marker)
        if hit is marker:
            todo.append(cid)
        else:
            found[cid] = bool(hit)
    if todo:
        pool = ThreadPoolExecutor(max_workers=min(LOOKUP_WORKERS, len(todo)))
        futures = {pool.submit(picture_url, broker, cid): cid for cid in todo}
        deadline = time.monotonic() + budget
        done, _ = wait(futures, timeout=max(0.0, deadline - time.monotonic()))
        pool.shutdown(wait=False)
        for future, cid in futures.items():
            found[cid] = future in done and future.exception() is None and bool(future.result())
    for chat in chats:
        chat["hasImage"] = found.get(chat.get("id"), False)
    return chats



CUSTOM_EMOJI_VIEWS = {True: "imgt2_anim", False: "img_thumb_tiny"}
MAX_EMOJI_BYTES = 2 * 1024 * 1024


def custom_emoji(broker, document_id: str, animated: bool) -> bytes | None:
    """A tenant custom emoji's picture from the Teams media service (`document_id` already validated), or None when it is gone. An animated view is a real GIF/WEBP, not a sprite."""
    try:
        return _custom_emoji(broker, document_id, animated)
    except ChatServiceError as ex:
        if ex.status != 401:
            raise
    return _custom_emoji(broker, document_id, animated)


def _custom_emoji(broker, document_id: str, animated: bool) -> bytes | None:
    skype, _ = _session(broker)
    base = for_broker(broker).get("teams_ams")
    if not base:
        raise ChatServiceError(404, "no media service for this account")
    url = f"{base}/v1/objects/{quote(document_id, safe='')}/views/{CUSTOM_EMOJI_VIEWS[animated]}"
    with http_client().stream("GET", url, headers={"Authorization": f"skype_token {skype}"}, timeout=_TIMEOUT, follow_redirects=False) as r:
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            if r.status_code == 401:
                _drop_session(broker)
            raise ChatServiceError(r.status_code, "custom emoji download failed")
        data = bytearray()
        for chunk in r.iter_bytes():
            data.extend(chunk)
            if len(data) > MAX_EMOJI_BYTES:
                raise ChatServiceError(413, "custom emoji larger than 2 MB")
    return bytes(data)
