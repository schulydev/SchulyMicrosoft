"""OneNote over Graph: notebooks (the person's own and each joined team's), the section tree, pages,
page content, resources, title search and page writes.

Ids. A team's notebooks (a class notebook is one) live under `groups/{id}/onenote`, the person's own
under `me/onenote`. Every id handed out says which: the bare Graph id for the person's own, and
`<group id>@<graph id>` for a team's. Ids go into Graph paths, so each is checked before use.

Lists the screen asks for again and again (notebooks, a root's sections and section groups, a
section's page titles for search) are kept on the account for a short while: OneNote throttles a
person who reads their whole notebook list several times a minute, and a class notebook is slow
enough already. Any write drops them.
"""

import html
import re
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
from entrance import http_client
from outnote import C_ONENOTE, GraphError

from src import onenote_html
from src.account_cache import for_broker

ID_PATTERN = re.compile(r"[A-Za-z0-9!@_{}:.\-]{1,300}")
GRAPH_ID = re.compile(r"[A-Za-z0-9!_{}:.\-]{1,200}")
GROUP_ID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
GRAPH = "https://graph.microsoft.com/v1.0"
KEEP = 90.0
TEAMS_KEEP = 600.0
MAX_SECTIONS = 2000
MAX_GROUP_DEPTH = 6
MAX_TITLE = 255
SEARCH_SECTIONS = 40
TEAM_WORKERS = 3
RESOURCE_RETRIES = 2
NOTEBOOK_FIELDS = "id,displayName,createdDateTime,lastModifiedDateTime,isDefault,isShared,userRole,links"
TREE_FIELDS = "id,displayName,lastModifiedDateTime"
PAGE_FIELDS = "id,title,createdDateTime,lastModifiedDateTime,level,order,links"
PARENTS = "parentNotebook($select=id),parentSectionGroup($select=id)"
HIT_EXPAND = "parentSection($select=id,displayName),parentNotebook($select=id,displayName)"


class OneNoteError(Exception):
    """A refusal the caller should see as such (not a Graph outage)."""

    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(message)


class ResourceTooLarge(Exception):
    pass


def parse_id(value: str) -> tuple[str | None, str]:
    """(group id or None, Graph id) of an id handed out; ValueError when it is not one."""
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value) or ".." in value or value.count("@") > 1:
        raise ValueError("invalid id")
    group, sep, graph_id = value.rpartition("@")
    if sep and not GROUP_ID.fullmatch(group):
        raise ValueError("invalid id")
    if not GRAPH_ID.fullmatch(graph_id) or graph_id in (".", ".."):
        raise ValueError("invalid id")
    return (group.lower() if sep else None), graph_id


def is_id(value: str) -> bool:
    try:
        parse_id(value)
        return True
    except ValueError:
        return False


def root(group: str | None) -> str:
    return f"groups/{group}/onenote" if group else "me/onenote"


def tag(group: str | None, graph_id: str | None) -> str | None:
    return onenote_html.scoped(group, graph_id) if graph_id else None


def web_url(links) -> str | None:
    href = ((links or {}).get("oneNoteWebUrl") or {}).get("href")
    return href if isinstance(href, str) and href.startswith("https://") and len(href) < 4000 else None


def _kept(broker, key, make, ttl: float = KEEP):
    cache = for_broker(broker)
    hit = cache.get(key)
    if hit is not None:
        return hit
    with cache.lock(repr(key)):
        hit = cache.get(key)
        if hit is not None:
            return hit
        value = make()
        cache.set(key, value, ttl)
        return value


def changed(broker):
    """What was read before a write is not what is there after it."""
    for_broker(broker).discard(lambda key: isinstance(key, tuple) and key[:1] == ("onenote",) and key[1:2] != ("teams",))


def _ref(group, obj) -> dict | None:
    if not isinstance(obj, dict) or not obj.get("id"):
        return None
    return {"id": tag(group, obj["id"]), "displayName": obj.get("displayName") or ""}


# --- notebooks -------------------------------------------------------------------------------


def _teams(note, broker) -> list[dict]:
    def make():
        try:
            rows = note.list("me/joinedTeams", {"$select": "id,displayName"}, limit=200)
        except GraphError:
            return []
        return [{"id": t["id"].lower(), "name": t.get("displayName")} for t in rows if isinstance(t.get("id"), str) and GROUP_ID.fullmatch(t["id"])]

    return _kept(broker, ("onenote", "teams"), make, TEAMS_KEEP)


def _notebook(group, team_name, n) -> dict:
    role = n.get("userRole")
    return {
        "id": tag(group, n["id"]),
        "displayName": n.get("displayName") or "",
        "createdDateTime": n.get("createdDateTime"),
        "lastModifiedDateTime": n.get("lastModifiedDateTime"),
        "isDefault": n.get("isDefault") is True,
        "isShared": n.get("isShared") is True,
        "userRole": role if role in ("Owner", "Contributor", "Reader") else None,
        "writable": role != "Reader",
        "webUrl": web_url(n.get("links")),
        "source": {"kind": "team" if group else "personal", "id": group, "name": team_name},
    }


def notebooks(note, broker, teams: bool = True) -> list[dict]:
    def make():
        own = note.list(f"{root(None)}/notebooks", {"$select": NOTEBOOK_FIELDS}, limit=500, client=C_ONENOTE)
        out = [_notebook(None, None, n) for n in own if GRAPH_ID.fullmatch(str(n.get("id", "")))]
        out.sort(key=lambda n: n["displayName"].lower())
        if not teams:
            return out
        joined = _teams(note, broker)

        def team_books(team):
            try:
                rows = note.list(f"{root(team['id'])}/notebooks", {"$select": NOTEBOOK_FIELDS}, limit=200, client=C_ONENOTE)
            except GraphError:
                # A team whose notebooks cannot be listed is somewhere the person has no notebook to open.
                return []
            return [_notebook(team["id"], team["name"], n) for n in rows if GRAPH_ID.fullmatch(str(n.get("id", "")))]

        # A few at a time: OneNote answers a burst of requests from one person with a wait.
        with ThreadPoolExecutor(max_workers=TEAM_WORKERS) as pool:
            found = list(pool.map(team_books, joined))
        for team, rows in sorted(zip(joined, found), key=lambda pair: (pair[0]["name"] or "").lower()):
            out.extend(sorted(rows, key=lambda n: n["displayName"].lower()))
        return out

    return _kept(broker, ("onenote", "notebooks", teams), make)


# --- section tree ----------------------------------------------------------------------------


def _flat(note, broker, group, what: str) -> list[dict]:
    """Every section or section group of a root, with its parents, kept a short while."""
    return _kept(broker, ("onenote", what, group), lambda: note.list(f"{root(group)}/{what}", {"$select": TREE_FIELDS + (",isDefault" if what == "sections" else ""), "$expand": PARENTS, "$top": 100}, limit=MAX_SECTIONS, client=C_ONENOTE))


def _walk_groups(note, group, notebook_id) -> list[dict]:
    """A notebook's section groups level by level, for when the root's collection of all of them fails (Graph answers it with a transient 500 for some personal accounts)."""
    out, level = [], [(f"{root(group)}/notebooks/{notebook_id}/sectionGroups", None)]
    for _ in range(MAX_GROUP_DEPTH):
        nxt = []
        for path, parent in level:
            for g in note.list(path, {"$select": TREE_FIELDS}, limit=500, client=C_ONENOTE):
                if not GRAPH_ID.fullmatch(str(g.get("id", ""))):
                    continue
                out.append({**g, "parentNotebook": {"id": notebook_id}, "parentSectionGroup": {"id": parent} if parent else None})
                nxt.append((f"{root(group)}/sectionGroups/{g['id']}/sectionGroups", g["id"]))
        level = nxt
        if not level:
            break
    return out


def tree(note, broker, notebook: str) -> dict:
    group, notebook_id = parse_id(notebook)
    sections = _flat(note, broker, group, "sections")
    if group is None:
        # The person's own collection of all section groups also holds what others shared, and Graph often answers it with a
        # transient 500 after a long wait: one notebook's groups are walked instead (most have none, which is one request).
        groups = _kept(broker, ("onenote", "walked", group, notebook_id), lambda: _walk_groups(note, group, notebook_id))
    else:
        # A team's collection holds its own notebooks only, and walking a class notebook's dozens of groups is dozens of requests.
        groups = _flat(note, broker, group, "sectionGroups")
    mine = lambda row: ((row.get("parentNotebook") or {}).get("id")) == notebook_id  # noqa: E731
    sections = [s for s in sections if mine(s)]
    groups = [g for g in groups if mine(g)]
    nodes = {}
    for g in groups:
        if GRAPH_ID.fullmatch(str(g.get("id", ""))):
            nodes[g["id"]] = {"id": tag(group, g["id"]), "kind": "group", "displayName": g.get("displayName") or "", "lastModifiedDateTime": g.get("lastModifiedDateTime"), "isDefault": False, "children": [], "_parent": (g.get("parentSectionGroup") or {}).get("id")}
    top: list[dict] = []
    for s in sections:
        if not GRAPH_ID.fullmatch(str(s.get("id", ""))):
            continue
        node = {"id": tag(group, s["id"]), "kind": "section", "displayName": s.get("displayName") or "", "lastModifiedDateTime": s.get("lastModifiedDateTime"), "isDefault": s.get("isDefault") is True, "children": []}
        parent = nodes.get((s.get("parentSectionGroup") or {}).get("id"))
        (parent["children"] if parent else top).append(node)
    top_groups = []
    for g in nodes.values():
        parent = nodes.get(g["_parent"]) if g["_parent"] != g["id"] else None
        (parent["children"] if parent else top_groups).append(g)

    def finish(node, depth=0):
        node.pop("_parent", None)
        if depth >= MAX_GROUP_DEPTH:
            node["children"] = []
        # OneNote lists a group's sections before its groups.
        node["children"].sort(key=lambda c: c["kind"] == "group")
        for c in node["children"]:
            finish(c, depth + 1)
        return node

    return {"notebookId": notebook, "children": top + [finish(g) for g in top_groups]}


# --- pages -----------------------------------------------------------------------------------


def _summary(group, section, p) -> dict:
    level = p.get("level")
    order = p.get("order")
    return {
        "id": tag(group, p["id"]),
        "title": p.get("title") or "",
        "level": level if isinstance(level, int) and 0 <= level <= 10 else 0,
        "order": order if isinstance(order, int) else None,
        "createdDateTime": p.get("createdDateTime"),
        "lastModifiedDateTime": p.get("lastModifiedDateTime"),
        "webUrl": web_url(p.get("links")),
        "sectionId": section,
    }


def pages(note, section: str, top: int, skip: int) -> dict:
    group, section_id = parse_id(section)
    answer = note.get(f"{root(group)}/sections/{section_id}/pages", {"$select": PAGE_FIELDS, "pagelevel": "true", "$top": top, "$skip": skip or None}, client=C_ONENOTE) or {}
    rows = [p for p in answer.get("value") or [] if GRAPH_ID.fullmatch(str(p.get("id", "")))]
    items = [_summary(group, section, p) for p in rows]
    return {"items": items, "nextSkip": skip + len(answer.get("value") or []) if answer.get("@odata.nextLink") else None}


def _meta(note, group, page_id) -> dict:
    return note.get(f"{root(group)}/pages/{page_id}", {"$select": "id,title,createdDateTime,lastModifiedDateTime,links", "$expand": "parentSection($select=id,displayName),parentNotebook($select=id,displayName,userRole)"}, client=C_ONENOTE) or {}


def _content(note, group, page_id, ink: bool = True) -> tuple[str, str | None]:
    path = f"{root(group)}/pages/{page_id}/content"
    page = note.get(path, {"includeIDs": "true"}, raw=True, client=C_ONENOTE) or ""
    if not ink or not onenote_html.has_ink(page):
        return page, None
    # The strokes are most of a drawn page's weight, so they are asked for only when the page has some.
    return onenote_html.split_parts(note.get(path, {"includeIDs": "true", "includeInkML": "true"}, raw=True, client=C_ONENOTE) or "")


def page(note, page_scoped: str) -> dict:
    group, page_id = parse_id(page_scoped)
    meta = _meta(note, group, page_id)
    content, ink = _content(note, group, page_id)
    rendered = onenote_html.render_page(content, ink, group)
    role = (meta.get("parentNotebook") or {}).get("userRole")
    return {
        "id": page_scoped,
        "title": meta.get("title") or rendered["title"],
        "createdDateTime": meta.get("createdDateTime"),
        "lastModifiedDateTime": meta.get("lastModifiedDateTime"),
        "webUrl": web_url(meta.get("links")),
        "section": _ref(group, meta.get("parentSection")),
        "notebook": _ref(group, meta.get("parentNotebook")),
        "writable": role != "Reader",
        "html": rendered["html"],
        "width": rendered["width"],
        "height": rendered["height"],
        "resources": rendered["resources"],
        "outlines": rendered["outlines"],
        "hasInk": rendered["hasInk"],
    }


def check_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title or "").strip()
    if not title or len(title) > MAX_TITLE:
        raise OneNoteError(400, f"A page title is 1-{MAX_TITLE} characters.")
    return title


def create_page(note, broker, section: str, title: str, body: str | None) -> dict:
    group, section_id = parse_id(section)
    made = note.post(f"{root(group)}/sections/{section_id}/pages", onenote_html.new_page(check_title(title), body), client=C_ONENOTE, content_type="application/xhtml+xml") or {}
    changed(broker)
    if not GRAPH_ID.fullmatch(str(made.get("id", ""))):
        raise OneNoteError(502, "OneNote did not return the new page.")
    return _summary(group, section, made)


def update_page(note, broker, page_scoped: str, title: str | None, outlines: list[dict] | None, append: str | None) -> dict:
    group, page_id = parse_id(page_scoped)
    meta = _meta(note, group, page_id)
    if (meta.get("parentNotebook") or {}).get("userRole") == "Reader":
        raise OneNoteError(403, "This notebook is read only.")
    commands = []
    if title is not None:
        commands.append({"target": "title", "action": "replace", "content": html.escape(check_title(title), quote=False)})
    if outlines:
        current, _ = _content(note, group, page_id, ink=False)
        for item in outlines:
            style = onenote_html.outline_style(current, item["id"])
            if style is None:
                raise OneNoteError(400, "That text box is not on the page or holds more than text, so it is not changed.")
            inner = onenote_html.sanitize_for_write(item["html"])
            commands.append({"target": item["id"], "action": "replace", "content": f'<div style="{style}">{inner}</div>' if style else f"<div>{inner}</div>"})
    if append and append.strip():
        inner = onenote_html.sanitize_for_write(append)
        if inner.strip():
            commands.append({"target": "body", "action": "append", "content": f"<div>{inner}</div>"})
    if commands:
        note.patch(f"{root(group)}/pages/{page_id}/content", commands, client=C_ONENOTE)
        changed(broker)
    return page(note, page_scoped)


def delete_page(note, broker, page_scoped: str):
    group, page_id = parse_id(page_scoped)
    note.delete(f"{root(group)}/pages/{page_id}", client=C_ONENOTE)
    changed(broker)


# --- resources -------------------------------------------------------------------------------


def resource(broker, resource_scoped: str, limit: int) -> bytes:
    """A picture's or a file's bytes, streamed from Graph's own host with the OneNote token and cut off past `limit`."""
    group, resource_id = parse_id(resource_scoped)
    url = f"{GRAPH}/{root(group)}/resources/{resource_id}/$value"
    for attempt in range(RESOURCE_RETRIES + 1):
        headers = {"Authorization": f"Bearer {broker(C_ONENOTE)}"}
        # No redirects: the bearer token must never follow a response to another host.
        with http_client().stream("GET", url, headers=headers, timeout=httpx.Timeout(60.0, connect=5.0), follow_redirects=False) as r:
            if r.status_code in (429, 503) and attempt < RESOURCE_RETRIES:
                wait = r.headers.get("Retry-After", "")
                time.sleep(min(6.0, float(wait)) if wait.isdigit() else 1.0 + attempt)
                continue
            if r.status_code >= 300:
                raise GraphError(r.status_code if r.status_code >= 400 else 502, "resource")
            size = r.headers.get("Content-Length", "")
            if size.isdigit() and int(size) > limit:
                raise ResourceTooLarge()
            data = bytearray()
            for chunk in r.iter_bytes(64 * 1024):
                data.extend(chunk)
                if len(data) > limit:
                    raise ResourceTooLarge()
            return bytes(data)
    raise GraphError(429, "resource")


# --- search ----------------------------------------------------------------------------------


def _hit(group, p) -> dict:
    return {"id": tag(group, p["id"]), "title": p.get("title") or "", "lastModifiedDateTime": p.get("lastModifiedDateTime"), "webUrl": web_url(p.get("links")), "section": _ref(group, p.get("parentSection")), "notebook": _ref(group, p.get("parentNotebook"))}


def _filtered(note, group, query: str, top: int) -> list[dict]:
    literal = query.lower().replace("'", "''")
    rows = note.list(f"{root(group)}/pages", {"$filter": f"contains(tolower(title),'{literal}')", "$select": "id,title,lastModifiedDateTime,links", "$expand": HIT_EXPAND, "$top": min(top, 100)}, limit=top, client=C_ONENOTE)
    return [p for p in rows if GRAPH_ID.fullmatch(str(p.get("id", "")))]


def _filter_refused(ex: GraphError) -> bool:
    """Graph's title filter covers a whole root and refuses one with too many sections, or with one section it cannot sync."""
    return ex.status in (400, 422)


def _walk_search(note, broker, group, notebook_id, query: str, top: int) -> tuple[list[dict], bool]:
    """Title search one section at a time (of one notebook, or of the whole root), for where Graph's own filter is refused."""
    flat = [s for s in _flat(note, broker, group, "sections") if notebook_id is None or (s.get("parentNotebook") or {}).get("id") == notebook_id]
    flat.sort(key=lambda s: s.get("lastModifiedDateTime") or "", reverse=True)
    partial = len(flat) > SEARCH_SECTIONS
    needle = query.lower()

    def titles(s):
        try:
            return _kept(broker, ("onenote", "titles", group, s["id"]), lambda: note.list(f"{root(group)}/sections/{s['id']}/pages", {"$select": "id,title,lastModifiedDateTime,links", "$top": 100}, limit=500, client=C_ONENOTE))
        except GraphError:
            return None

    # A few sections at a time, most recently changed first; their page titles are kept a short while for the next search.
    with ThreadPoolExecutor(max_workers=TEAM_WORKERS) as pool:
        found = list(pool.map(titles, flat[:SEARCH_SECTIONS]))
    hits = []
    for s, rows in zip(flat, found):
        if rows is None:
            # A section OneNote cannot sync is not one the person has pages in to find.
            continue
        parent = (s.get("parentNotebook") or {}).get("id")
        for p in rows:
            if needle in (p.get("title") or "").lower() and GRAPH_ID.fullmatch(str(p.get("id", ""))):
                hits.append(_hit(group, {**p, "parentSection": {"id": s["id"], "displayName": s.get("displayName")}, "parentNotebook": {"id": parent, "displayName": None} if parent else None}))
    hits.sort(key=lambda h: h.get("lastModifiedDateTime") or "", reverse=True)
    return hits[:top], partial


def _name_notebooks(note, broker, hits: list[dict]):
    names = {n["id"]: n["displayName"] for n in notebooks(note, broker)}
    for h in hits:
        if h["notebook"] and not h["notebook"]["displayName"]:
            h["notebook"]["displayName"] = names.get(h["notebook"]["id"], "")


def search(note, broker, query: str, notebook: str | None, top: int) -> dict:
    query = re.sub(r"\s+", " ", query).strip()
    if notebook:
        group, notebook_id = parse_id(notebook)
        try:
            rows = [p for p in _filtered(note, group, query, 100) if (p.get("parentNotebook") or {}).get("id") == notebook_id]
            return {"items": [_hit(group, p) for p in rows[:top]], "partial": False}
        except GraphError as ex:
            if not _filter_refused(ex):
                raise
        hits, partial = _walk_search(note, broker, group, notebook_id, query, top)
        _name_notebooks(note, broker, hits)
        return {"items": hits, "partial": partial}
    roots = [None] + [t["id"] for t in _teams(note, broker)]

    def one(group):
        try:
            return [_hit(group, p) for p in _filtered(note, group, query, top)], False
        except GraphError as ex:
            if not _filter_refused(ex):
                if group is None:
                    raise
                return [], True
        if group is None:
            # The person's own notebooks are few sections, so they are walked; a class notebook is searched by picking it.
            return _walk_search(note, broker, None, None, query, top)
        return [], True

    with ThreadPoolExecutor(max_workers=TEAM_WORKERS) as pool:
        found = list(pool.map(one, roots))
    items = [h for rows, _ in found for h in rows]
    _name_notebooks(note, broker, items)
    items.sort(key=lambda h: h.get("lastModifiedDateTime") or "", reverse=True)
    return {"items": items[:top], "partial": any(p for _, p in found)}
