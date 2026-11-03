"""Search over files, mail, chats and channel posts with the Microsoft Search API, with the place each hit lives in.

Files (`driveItem`) and messages (`message` + `chatMessage`) can't share one Search API request ("Invalid entity type combination"),
so they run as two requests in parallel; a source that fails is reported in `errors` and never fails the search. When the Search API
refuses the file search (400 / 403 / 5xx), the user's drive and each joined team's library are searched one by one instead. The query
text is never logged; it only travels in the request body to Microsoft (and, for the drive fallback, in a Graph URL).
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from urllib.parse import quote, unquote
from outnote import GraphError

from src.application.abstractions.i_graph_search import IGraphSearch
from src.application.abstractions.i_teams_files import ITeamsFiles
from src.infrastructure.microsoft.account_cache import AccountCache


class Context:
    """Lazily loaded lookups shared by the hits of one search; each failure only costs the detail it would have given."""

    def __init__(self, note, broker, teams_files: ITeamsFiles):
        self.note, self.cache = note, AccountCache.for_broker(broker)
        self.broker = broker
        self._teams_files = teams_files
        self._own = self._drives = self._shared = None
        self._teams = None
        self._channels: dict[str, dict[str, str]] = {}

    def teams(self) -> dict[str, str]:
        if self._teams is None:
            try:
                self._teams = {t["id"]: t.get("displayName") or "" for t in self._teams_files.joined_teams(self.note, self.broker)}
            except Exception as ex:
                GraphSearch.log.info("search: joined teams failed: %s", type(ex).__name__)
                self._teams = {}
        return self._teams

    def own_drive(self):
        if self._own is None:
            try:
                self._own = self._teams_files.own_drive_id(self.note, self.broker) or ""
            except Exception as ex:
                GraphSearch.log.info("search: own drive failed: %s", type(ex).__name__)
                self._own = ""
        return self._own

    def team_drives(self) -> dict[str, str]:
        """Library drive id -> team id for the joined teams (cached 1 h)."""
        if self._drives is None:
            hit = self.cache.get(("search", "team_drives"))
            if hit is None:
                hit = {}
                complete = True

                def one(team_id):
                    try:
                        return team_id, self._teams_files.team_drive_id(self.note, self.broker, team_id)
                    except Exception:
                        return team_id, None

                with ThreadPoolExecutor(max_workers=GraphSearch.FALLBACK_WORKERS) as pool:
                    for team_id, drive_id in pool.map(one, list(self.teams())):
                        if drive_id:
                            hit[drive_id] = team_id
                        else:
                            complete = False
                self.cache.set(("search", "team_drives"), hit, GraphSearch.MAP_TTL if complete else 300)
            self._drives = hit
        return self._drives

    def channel_names(self, team_id: str) -> dict[str, str]:
        """Channel id -> name (cached through `ITeamsFiles.channels`)."""
        if team_id not in self._channels:
            try:
                self._channels[team_id] = {c["id"]: c.get("displayName") or "" for c in self._teams_files.channels(self.note, self.broker, team_id)}
            except Exception as ex:
                GraphSearch.log.info("search: channels failed: %s", type(ex).__name__)
                self._channels[team_id] = {}
        return self._channels[team_id]

    def shared_ids(self) -> set[str]:
        if self._shared is None:
            hit = self.cache.get(("search", "shared_ids"))
            if hit is None:
                try:
                    hit = {i["id"] for i in self._teams_files.shared_with_me(self.note, 200)}
                except Exception as ex:
                    GraphSearch.log.info("search: sharedWithMe failed: %s", type(ex).__name__)
                    hit = set()
                self.cache.set(("search", "shared_ids"), hit, GraphSearch.SHARED_TTL)
            self._shared = hit
        return self._shared


class GraphSearch(IGraphSearch):
    """The Search API over files, mail, chats and channel posts, with hit locations and a per-drive fallback. Never logs the query."""

    log = logging.getLogger("schuly.microsoft")
    SNIPPET_MAX = 300
    MAP_TTL = 3600
    SHARED_TTL = 600
    FALLBACK_WORKERS = 4
    FALLBACK_PER_DRIVE = 50
    TEAM_SEARCH_CAP = 200
    TAGS = re.compile(r"<[^>]*>")
    TYPES = ("files", "mail", "chats", "channels")

    def __init__(self, teams_files: ITeamsFiles):
        self._teams_files = teams_files

    def snippet(self, summary) -> str:
        """The Search API's summary as plain text: `<ddd/>` becomes an ellipsis, highlight and other tags go, entities are decoded."""
        if not isinstance(summary, str):
            return ""
        text = summary.replace("<ddd/>", "…")
        text = unescape(self.TAGS.sub("", text))
        text = " ".join(text.split())
        return text if len(text) <= self.SNIPPET_MAX else text[: self.SNIPPET_MAX - 1].rstrip() + "…"

    def reason(self, ex: Exception) -> str:
        if isinstance(ex, GraphError):
            if ex.status in (401, 403):
                return f"not permitted ({ex.status})"
            if ex.status == 429:
                return "throttled (429)"
            if ex.status >= 500:
                return f"service error ({ex.status})"
            return f"request refused ({ex.status})"
        return "request failed"

    def _sender(self, person):
        """`{displayName, email}` out of a Graph emailAddress wrapper, an identitySet or a bare user."""
        if not isinstance(person, dict):
            return None
        inner = person.get("emailAddress") or person.get("user") or person
        name, mail = inner.get("name") or inner.get("displayName"), inner.get("address") or inner.get("email")
        return {"displayName": name, "email": mail} if name or mail else None

    def _identity(self, value):
        return self._sender(value) if isinstance(value, dict) else None

    def _query(self, note, entities: list[str], q: str, start: int, size: int):
        """One Search API request: (hits, total, more)."""
        body = {"requests": [{"entityTypes": entities, "query": {"queryString": q}, "from": start, "size": size}]}
        data = note.post("search/query", body) or {}
        hits, total, more = [], 0, False
        for container in ((data.get("value") or [{}])[0].get("hitsContainers") or []):
            hits.extend(container.get("hits") or [])
            total += int(container.get("total") or 0)
            more = more or bool(container.get("moreResultsAvailable"))
        return hits, total, more

    def file_hit(self, hit: dict) -> dict | None:
        r = hit.get("resource") if isinstance(hit.get("resource"), dict) else {}
        ref = r.get("parentReference") or {}
        item_id = r.get("id") or hit.get("hitId")
        if not item_id:
            return None
        out = {"type": "file", "id": item_id, "driveId": ref.get("driveId"), "title": r.get("name"), "snippet": self.snippet(hit.get("summary")), "date": r.get("lastModifiedDateTime"), "webUrl": r.get("webUrl"), "size": r.get("size"), "isFolder": r.get("folder") is not None, "mimeType": (r.get("file") or {}).get("mimeType"), "from": self._identity(r.get("lastModifiedBy") or r.get("createdBy"))}
        path = ref.get("path")
        if isinstance(path, str) and "root:" in path:
            out["_path"] = self._clean_path(path)
        return out

    def _clean_path(self, raw: str) -> str:
        return unquote(raw.split("root:", 1)[1]).strip("/")

    def message_hit(self, hit: dict) -> dict | None:
        r = hit.get("resource") if isinstance(hit.get("resource"), dict) else {}
        kind = str(r.get("@odata.type") or "")
        mid = r.get("id") or hit.get("hitId")
        if not mid:
            return None
        if kind.endswith("chatMessage") or "channelIdentity" in r or "chatId" in r:
            sender = self._sender(r.get("from"))
            channel = r.get("channelIdentity") if isinstance(r.get("channelIdentity"), dict) else None
            return {"type": "channel" if channel else "chat", "id": mid, "title": r.get("subject") or (sender or {}).get("displayName") or "Chat", "snippet": self.snippet(hit.get("summary")), "date": r.get("createdDateTime"), "webUrl": r.get("webLink") or r.get("webUrl"), "from": sender, "_channel": channel, "_chatId": r.get("chatId")}
        return {"type": "mail", "id": mid, "title": r.get("subject"), "snippet": self.snippet(hit.get("summary") or r.get("bodyPreview")), "date": r.get("receivedDateTime") or r.get("sentDateTime"), "webUrl": r.get("webLink"), "from": self._sender(r.get("from"))}

    def _paths(self, note, hits: list[dict]):
        """Fills `_path` of file hits that have none through `$batch` (parentReference.path is not in Search API results)."""
        missing = [h for h in hits if h.get("driveId") and "_path" not in h]
        if not missing:
            return
        try:
            rows = note.batch([f"drives/{self._teams_files.seg(h['driveId'])}/items/{self._teams_files.seg(h['id'])}?$select=id,parentReference" for h in missing])
        except Exception as ex:
            self.log.info("search: path lookup failed: %s", type(ex).__name__)
            return
        for h, row in zip(missing, rows):
            path = ((row or {}).get("parentReference") or {}).get("path") if isinstance(row, dict) else None
            if isinstance(path, str) and "root:" in path:
                h["_path"] = self._clean_path(path)
            elif isinstance(path, str) and path.endswith("/root"):
                h["_path"] = ""

    def _join(self, *parts) -> str:
        return " > ".join(p for p in parts if p)

    def locate(self, hits: list[dict], ctx: Context):
        """Adds `location` to every hit and drops the helper keys."""
        files = [h for h in hits if h["type"] == "file"]
        if files:
            self._paths(ctx.note, files)
        own = ctx.own_drive() if files else ""
        drives = ctx.team_drives() if any(h.get("driveId") and h["driveId"] != own for h in files) else {}
        for h in hits:
            if h["type"] == "file":
                path = h.pop("_path", None)
                drive = h.get("driveId")
                loc = {"path": path}
                if drive and drive == own:
                    loc["kind"] = "onedrive"
                    loc["label"] = self._join("OneDrive", path)
                elif drive in drives:
                    team_id = drives[drive]
                    name = ctx.teams().get(team_id) or ""
                    loc.update(kind="team", teamId=team_id, teamName=name)
                    top = (path or "").split("/", 1)[0]
                    if top:
                        for cid, cname in ctx.channel_names(team_id).items():
                            if cname == top:
                                loc.update(channelId=cid, channelName=cname)
                                break
                    loc["label"] = self._join(f"Team {name}" if name else "Team", path)
                elif h["id"] in ctx.shared_ids():
                    loc["kind"] = "shared"
                    loc["label"] = self._join("Shared with me", path)
                else:
                    loc["kind"] = "sharepoint"
                    loc["label"] = self._join("SharePoint", path)
                h["location"] = loc
            elif h["type"] == "mail":
                h["location"] = {"kind": "mailbox", "label": "Mailbox"}
            elif h["type"] == "channel":
                channel = h.pop("_channel", None) or {}
                h.pop("_chatId", None)
                team_id, channel_id = channel.get("teamId"), channel.get("channelId")
                team_name = ctx.teams().get(team_id) if team_id else None
                channel_name = ctx.channel_names(team_id).get(channel_id) if team_id and channel_id else None
                h["location"] = {"kind": "channel", "teamId": team_id, "teamName": team_name, "channelId": channel_id, "channelName": channel_name, "label": self._join(f"Team {team_name}" if team_name else "Team", channel_name)}
            else:
                chat_id = h.pop("_chatId", None)
                h.pop("_channel", None)
                h["location"] = {"kind": "chat", "chatId": chat_id, "label": "Chat"}

    def drive_search(self, note, drive_id: str | None, q: str, top: int) -> list[dict]:
        """Hits of `drives/{d}/root/search(q=)` (or the user's own drive when `drive_id` is None) shaped like Search API hits."""
        literal = quote(q.replace("'", "''"), safe="")
        base = f"drives/{self._teams_files.seg(drive_id)}" if drive_id else "me/drive"
        rows = note.list(f"{base}/root/search(q='{literal}')", {"$top": min(top, 200), "$select": self._teams_files.ITEM_FIELDS}, limit=top)
        return [{"resource": self._teams_files._with_drive(r, drive_id)} for r in rows]

    def fallback_files(self, note, broker, q: str, ctx: Context):
        """Own drive + each joined team's library, searched in parallel; returns (hits, errors)."""
        targets: list[str | None] = [None]
        errors = []
        try:
            targets += list(ctx.team_drives())
        except Exception as ex:
            errors.append(f"teams: {self.reason(ex)}")

        def one(drive_id):
            try:
                return self.drive_search(note, drive_id, q, self.FALLBACK_PER_DRIVE), None
            except Exception as ex:
                if "invalid_grant" in str(ex):
                    raise
                return [], self.reason(ex)

        hits, failed = [], 0
        with ThreadPoolExecutor(max_workers=self.FALLBACK_WORKERS) as pool:
            for found, err in pool.map(one, targets):
                hits.extend(found)
                failed += 1 if err else 0
        if failed:
            errors.append(f"files: {failed} of {len(targets)} libraries could not be searched")
        return hits, errors

    def _by_date(self, hits: list[dict]) -> list[dict]:
        return sorted(hits, key=lambda h: (h.get("resource") or {}).get("lastModifiedDateTime") or "", reverse=True)

    def run(self, note, broker, q: str, types: list[str], start: int, size: int, team_id: str | None = None) -> dict:
        """The SearchResult for `q` over the wanted `types` (files, mail, chats, channels), optionally limited to one team."""
        wanted = [t for t in self.TYPES if t in types]
        if team_id:
            wanted = [t for t in wanted if t in ("files", "channels")]
        ctx = Context(note, broker, self._teams_files)
        errors: list[str] = []
        out: list[dict] = []
        totals = {"files": 0, "messages": 0}
        more = False
        fallback = False

        def files_source():
            if team_id:
                drive_id = self._teams_files.team_drive_id(note, broker, team_id)
                rows = self.drive_search(note, drive_id, q, min(start + size + 1, self.TEAM_SEARCH_CAP))
                page = rows[start : start + size]
                return page, len(rows), len(rows) > start + size, False
            try:
                hits, total, has_more = self._query(note, ["driveItem"], q, start, size)
                return hits, total, has_more, False
            except GraphError as ex:
                if ex.status in (400, 403) or ex.status >= 500:
                    found, errs = self.fallback_files(note, broker, q, ctx)
                    errors.extend(errs)
                    found = self._by_date(found)
                    return found[start : start + size], len(found), len(found) > start + size, True
                raise

        entities = []
        if "mail" in wanted:
            entities.append("message")
        if "chats" in wanted or "channels" in wanted:
            entities.append("chatMessage")

        def messages_source():
            hits, total, has_more = self._query(note, entities, q, start, size)
            return hits, total, has_more

        jobs = {}
        with ThreadPoolExecutor(max_workers=2) as pool:
            if "files" in wanted:
                jobs["files"] = pool.submit(files_source)
            if entities:
                jobs["messages"] = pool.submit(messages_source)
            results = {}
            for name, future in jobs.items():
                try:
                    results[name] = future.result()
                except Exception as ex:
                    if "invalid_grant" in str(ex):
                        raise
                    label = name if name == "files" else ("mail" if entities == ["message"] else "messages")
                    errors.append(f"{label}: {self.reason(ex)}")
        if "files" in results:
            hits, totals["files"], has_more, fallback = results["files"]
            more = more or has_more
            out.extend(h for h in (self.file_hit(x) for x in hits) if h)
        if "messages" in results:
            hits, totals["messages"], has_more = results["messages"]
            more = more or has_more
            for h in (self.message_hit(x) for x in hits):
                if h is None:
                    continue
                if h["type"] == "mail" and "mail" not in wanted:
                    continue
                if h["type"] == "chat" and "chats" not in wanted:
                    continue
                if h["type"] == "channel" and ("channels" not in wanted or (team_id and (h.get("_channel") or {}).get("teamId") != team_id)):
                    continue
                out.append(h)
        self.locate(out, ctx)
        out.sort(key=lambda h: h.get("date") or "", reverse=True)
        return {"query": q, "hits": out, "from": start, "size": size, "moreAvailable": more, "nextFrom": start + size if more else None, "totals": totals, "fallback": fallback, "errors": errors}
