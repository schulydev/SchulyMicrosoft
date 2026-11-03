"""Teams, channels and the files behind them (team libraries, channel folders), plus shared / recent files and raw drive items.

Live facts: `groups/{id}/drive` answers 404 on the Office client, so a team's library id is resolved with the OfficeHome client
(`C_SITES`) and cached for an hour; browsing `drives/{driveId}/...` then works on the default client. Every drive entry handed out
carries `parentReference.driveId` so the caller can address it again.
"""

import re
from urllib.parse import quote, urlsplit

import httpx
from outnote import C_SITES, GraphError

from src import outnote_client
from src.account_cache import for_broker

LIST_TTL = 600
DRIVE_TTL = 3600
MAX_PATH_CHARS = 400
MAX_PATH_SEGMENTS = 30
MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024
FETCH_TIMEOUT = httpx.Timeout(120.0, connect=5.0)
ITEM_FIELDS = "id,name,size,file,folder,webUrl,lastModifiedDateTime,createdDateTime,parentReference,lastModifiedBy,createdBy"
FORBIDDEN_PATH = re.compile(r"[%\\:#?\x00-\x1f\x7f]")


class FileFetchError(Exception):
    """A download that can't be served: `status` is the HTTP status to answer with."""

    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(message)


def seg(value: str) -> str:
    return quote(value, safe="")


def valid_path(path) -> list[str]:
    """The folder names of a relative path ('' -> none). Raises ValueError on dot segments, `% \\ : # ?`, control characters or a path over 400 chars."""
    if path is None or path == "":
        return []
    if not isinstance(path, str) or len(path) > MAX_PATH_CHARS or FORBIDDEN_PATH.search(path):
        raise ValueError("invalid path")
    parts = [p for p in path.split("/") if p != ""]
    if len(parts) > MAX_PATH_SEGMENTS or any(p in (".", "..") or ".." in p or p != p.strip() for p in parts):
        raise ValueError("invalid path")
    return parts


def is_download_url(url) -> bool:
    """True only for an https SharePoint download URL: host ends with `.sharepoint.com`, default port, no credentials."""
    if not isinstance(url, str) or not url or len(url) > 8000 or any(ord(c) < 33 for c in url):
        return False
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and port in (None, 443) and not parts.username and not parts.password and host.endswith(".sharepoint.com")


def fetch_bytes(url: str, cap: int) -> bytes:
    """The bytes behind a pre-authorized download URL (no bearer token, no redirects), 413 past `cap`."""
    if not is_download_url(url):
        raise FileFetchError(502, "The file has an unexpected download location.")
    out = bytearray()
    with outnote_client.download_client().stream("GET", url, timeout=FETCH_TIMEOUT, follow_redirects=False) as r:
        if r.status_code != 200:
            raise FileFetchError(502, f"The download failed ({r.status_code}).")
        for chunk in r.iter_bytes(64 * 1024):
            out.extend(chunk)
            if len(out) > cap:
                raise FileFetchError(413, "The file is too large.")
    return bytes(out)


def download_url(note, path: str, item: dict) -> str | None:
    """The pre-authorized link of the item at `path`, or None when `/content` answers without a redirect. Graph can leave it out of a `$select` answer, so ask again without one, then through `/content`; a refusal there is raised.

    OutNote 2.0.1's `download_url` has the same fallback but can't take the `shares/...` path chat files need and always asks Graph again, and its `download` holds the whole file in memory with no cap."""
    url = item.get("@microsoft.graph.downloadUrl")
    if url:
        return url
    full = note.get(path)
    url = full.get("@microsoft.graph.downloadUrl") if isinstance(full, dict) else None
    if url:
        return url
    try:
        return note.redirect(f"{path}/content")
    except GraphError as ex:
        if ex.status >= 400:
            raise
        return None


def item_base(drive_id: str | None, item_id: str) -> str:
    return f"drives/{seg(drive_id)}/items/{seg(item_id)}" if drive_id else f"me/drive/items/{seg(item_id)}"


def _with_drive(item: dict, drive_id: str | None) -> dict:
    if drive_id and isinstance(item, dict):
        ref = item.get("parentReference")
        if not isinstance(ref, dict):
            ref = item["parentReference"] = {}
        ref.setdefault("driveId", drive_id)
    return item


def joined_teams(note, broker) -> list[dict]:
    cache = for_broker(broker)
    hit = cache.get(("teams", "joined"))
    if hit is not None:
        return hit
    rows = note.list("me/joinedTeams", {"$select": "id,displayName,description"})
    teams = [{"id": t.get("id"), "displayName": t.get("displayName"), "description": t.get("description")} for t in rows if t.get("id")]
    cache.set(("teams", "joined"), teams, LIST_TTL)
    return teams


def channels(note, broker, team_id: str) -> list[dict]:
    cache = for_broker(broker)
    key = ("teams", "channels", team_id)
    hit = cache.get(key)
    if hit is not None:
        return hit
    rows = note.list(f"teams/{seg(team_id)}/channels", {"$select": "id,displayName,membershipType,description"})
    out = [{"id": c.get("id"), "displayName": c.get("displayName"), "membershipType": c.get("membershipType"), "description": c.get("description")} for c in rows if c.get("id")]
    cache.set(key, out, LIST_TTL)
    return out


def team_drive_id(note, broker, team_id: str) -> str:
    """The team's document library id (the Office client can't read `groups/{id}/drive`, the OfficeHome client can); cached 1 h."""
    cache = for_broker(broker)
    key = ("teams", "drive", team_id)
    hit = cache.get(key)
    if hit:
        return hit
    drive = note.get(f"groups/{seg(team_id)}/drive", {"$select": "id"}, client=C_SITES) or {}
    drive_id = drive.get("id")
    if not drive_id:
        raise GraphError(404, "The team has no document library.")
    cache.set(key, drive_id, DRIVE_TTL)
    return drive_id


def own_drive_id(note, broker) -> str | None:
    cache = for_broker(broker)
    key = ("drive", "own")
    hit = cache.get(key)
    if hit:
        return hit
    drive_id = (note.get("me/drive", {"$select": "id"}) or {}).get("id")
    if drive_id:
        cache.set(key, drive_id, DRIVE_TTL)
    return drive_id


def team_files(note, broker, team_id: str, channel_id: str | None, path: str | None, top: int) -> dict:
    """`{driveId, folder: {id, name, path}, items}` for a team's library root, or a channel's folder, or a sub-folder of either."""
    names = valid_path(path)
    if channel_id:
        root = note.get(f"teams/{seg(team_id)}/channels/{seg(channel_id)}/filesFolder", {"$select": "id,name,parentReference"}) or {}
        drive_id = (root.get("parentReference") or {}).get("driveId")
        if not drive_id or not root.get("id"):
            raise GraphError(404, "The channel has no files folder.")
    else:
        drive_id = team_drive_id(note, broker, team_id)
        root = note.get(f"drives/{seg(drive_id)}/root", {"$select": "id,name"}) or {}
        if not root.get("id"):
            raise GraphError(404, "The team library has no root.")
    folder = root
    if names:
        folder = note.get(f"drives/{seg(drive_id)}/items/{seg(root['id'])}:/{'/'.join(seg(n) for n in names)}", {"$select": "id,name,folder"}) or {}
        if folder.get("folder") is None or not folder.get("id"):
            raise GraphError(404, "Folder not found.")
    items = note.list(f"drives/{seg(drive_id)}/items/{seg(folder['id'])}/children", {"$top": min(top, 200), "$select": ITEM_FIELDS}, limit=top)
    return {"driveId": drive_id, "folder": {"id": folder["id"], "name": folder.get("name"), "path": "/".join(names)}, "items": [_with_drive(i, drive_id) for i in items]}


def drive_item(note, drive_id: str, item_id: str) -> dict:
    """One drive item with a fresh download URL."""
    return _with_drive(note.get(item_base(drive_id, item_id)) or {}, drive_id)


def children(note, drive_id: str, item_id: str, top: int) -> list[dict]:
    rows = note.list(f"{item_base(drive_id, item_id)}/children", {"$top": min(top, 200), "$select": ITEM_FIELDS}, limit=top)
    return [_with_drive(i, drive_id) for i in rows]


def _identity(value):
    """`{displayName, email}` out of a Graph identitySet (or a bare identity)."""
    if not isinstance(value, dict):
        return None
    user = value.get("user") if isinstance(value.get("user"), dict) else value
    name, email = user.get("displayName"), user.get("email")
    return {"displayName": name, "email": email} if name or email else None


def flatten(entry: dict) -> dict | None:
    """A sharedWithMe / recent row as a plain driveItem (the `remoteItem` unwrapped), always with `parentReference.driveId`."""
    remote = entry.get("remoteItem") if isinstance(entry.get("remoteItem"), dict) else entry
    ref = remote.get("parentReference") or entry.get("parentReference") or {}
    drive_id = ref.get("driveId")
    if not remote.get("id") or not drive_id:
        return None
    out = {"id": remote["id"], "name": remote.get("name") or entry.get("name"), "size": remote.get("size", entry.get("size")), "webUrl": remote.get("webUrl") or entry.get("webUrl"), "lastModifiedDateTime": remote.get("lastModifiedDateTime") or entry.get("lastModifiedDateTime"), "parentReference": {"driveId": drive_id}}
    if remote.get("file") is not None:
        out["file"] = remote["file"]
    if remote.get("folder") is not None:
        out["folder"] = remote["folder"]
    by = _identity(remote.get("lastModifiedBy") or entry.get("lastModifiedBy"))
    if by:
        out["lastModifiedBy"] = {"user": by}
    shared = remote.get("shared") or entry.get("shared") or {}
    sharer = _identity(shared.get("sharedBy") or shared.get("owner"))
    if sharer or shared.get("sharedDateTime"):
        out["shared"] = {"sharedBy": sharer, "sharedDateTime": shared.get("sharedDateTime")}
    return out


def shared_with_me(note, top: int) -> list[dict]:
    rows = note.list("me/drive/sharedWithMe", {"$top": min(top, 200)}, limit=top)
    return [f for f in (flatten(r) for r in rows) if f]


def recent(note, top: int) -> list[dict]:
    rows = note.list("me/drive/recent", {"$top": min(top, 200)}, limit=top)
    return [f for f in (flatten(r) for r in rows) if f]
