"""Search: normalization, locations, combined sources, errors and the per-drive fallback (mocked Graph)."""

import pytest
from fastapi.testclient import TestClient
from outnote import GraphError

from src import config, outnote_client, search
from src.app import app

H = {config.REFRESH_TOKEN_HEADER: "old-frt"}
TEAM = "11111111-2222-3333-4444-555555555555"
CH = "19:abc@thread.tacv2"
OWN, TEAMDRIVE, SHARED, OTHER = "b!OWN", "b!TEAM", "b!SHARED", "b!SITE"


def file_resource(item_id, drive, name="Masterplan.xlsx", path=None):
    ref = {"driveId": drive}
    if path is not None:
        ref["path"] = path
    return {"id": item_id, "name": name, "size": 9, "file": {"mimeType": "x/y"}, "webUrl": "https://w/" + item_id, "lastModifiedDateTime": "2026-10-01T08:00:00Z", "lastModifiedBy": {"user": {"displayName": "Ann", "email": "a@x.ch"}}, "parentReference": ref}


FILE_HITS = [
    {"hitId": "F1", "summary": "a <c0>Master</c0>plan<ddd/> &amp; more <b>x</b>", "resource": file_resource("F1", OWN)},
    {"hitId": "F2", "summary": "", "resource": file_resource("F2", TEAMDRIVE)},
    {"hitId": "F3", "summary": "", "resource": file_resource("F3", SHARED)},
    {"hitId": "F4", "summary": "", "resource": file_resource("F4", OTHER)},
]
MSG_HITS = [
    {"hitId": "M1", "summary": "<c0>Hi</c0>", "resource": {"@odata.type": "#microsoft.graph.message", "id": "M1", "subject": "Subj", "receivedDateTime": "2026-09-01T00:00:00Z", "from": {"emailAddress": {"name": "Bob", "address": "b@x.ch"}}, "webLink": "https://mail"}},
    {"hitId": "C1", "summary": "post", "resource": {"@odata.type": "#microsoft.graph.chatMessage", "id": "C1", "createdDateTime": "2026-09-02T00:00:00Z", "from": {"emailAddress": {"name": "Cy", "address": "c@x.ch"}}, "channelIdentity": {"teamId": TEAM, "channelId": CH}}},
    {"hitId": "C2", "summary": "dm", "resource": {"@odata.type": "#microsoft.graph.chatMessage", "id": "C2", "createdDateTime": "2026-09-03T00:00:00Z", "chatId": "19:chat@unq.gbl.spaces", "from": {"emailAddress": {"name": "Di", "address": "d@x.ch"}}}},
]


def container(hits, total=None, more=False):
    return {"value": [{"hitsContainers": [{"hits": hits, "total": total if total is not None else len(hits), "moreResultsAvailable": more}]}]}


class Broker:
    refresh_token = "old-frt"

    def __call__(self, client_id, scope=None):
        self.refresh_token = "rotated-frt"
        return "bearer"


class Note:
    def __init__(self, broker):
        self.broker = broker
        self.posts = []
        self.file_error = None
        self.msg_error = None
        self.drive_searches = []
        self.batch_fail = False
        self.team_search_fails = False

    def post(self, path, body=None, client=None):
        self.broker("x")
        assert path == "search/query"
        req = body["requests"][0]
        self.posts.append(req)
        kinds = req["entityTypes"]
        if kinds == ["driveItem"]:
            if self.file_error:
                raise self.file_error
            return container(FILE_HITS, 319, more=True)
        assert "driveItem" not in kinds
        if self.msg_error:
            raise self.msg_error
        return container(MSG_HITS, 11)

    def get(self, path, params=None, raw=False, client=None):
        self.broker("x")
        if path == "me/drive":
            return {"id": OWN}
        if path.startswith("groups/"):
            return {"id": TEAMDRIVE}
        raise GraphError(404, path)

    def list(self, path, params=None, limit=None, client=None):
        self.broker("x")
        if path == "me/joinedTeams":
            return [{"id": TEAM, "displayName": "BM23d ab 2025"}]
        if path.endswith("/channels"):
            return [{"id": CH, "displayName": "Deutsch"}]
        if path == "me/drive/sharedWithMe":
            return [{"remoteItem": {"id": "F3", "name": "x", "parentReference": {"driveId": SHARED}}}]
        if "/root/search(q=" in path:
            self.drive_searches.append(path)
            drive = OWN if path.startswith("me/") else TEAMDRIVE
            if drive == TEAMDRIVE and self.team_search_fails:
                raise GraphError(500, "x")
            return [file_resource("D-" + drive, drive, path=f"/drives/{drive}/root:/Deutsch")]
        return []

    def batch(self, requests):
        self.broker("x")
        if self.batch_fail:
            raise GraphError(500, "x")
        out = []
        for r in requests:
            if "F4" in r:
                out.append(GraphError(404, "gone"))
            else:
                out.append({"parentReference": {"path": "/drives/x/root:/Deutsch/Pr%C3%BCfungen"}})
        return out


@pytest.fixture
def env(monkeypatch):
    broker = Broker()
    note = Note(broker)
    monkeypatch.setattr(outnote_client, "build_client", lambda frt: (note, broker))
    return note, TestClient(app)


def by_id(body):
    return {h["id"]: h for h in body["hits"]}


def test_snippet_cleanup():
    assert search.snippet("a <c0>Master</c0>plan<ddd/> &amp; <b>x</b>") == "a Masterplan… & x"
    long = search.snippet("w " * 400)
    assert len(long) <= 300 and long.endswith("…")
    assert search.snippet(None) == ""


def test_files_and_messages_run_as_two_requests_with_locations(env):
    note, client = env
    r = client.post("/api/search", json={"q": " Masterplan ", "types": ["files", "mail", "chats", "channels"], "from": 0, "size": 25}, headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert r.headers["cache-control"] == "no-store" and r.headers[config.REFRESH_TOKEN_HEADER] == "rotated-frt"
    assert sorted(tuple(p["entityTypes"]) for p in note.posts) == [("driveItem",), ("message", "chatMessage")]
    assert body["query"] == "Masterplan" and body["totals"] == {"files": 319, "messages": 11}
    assert body["moreAvailable"] is True and body["nextFrom"] == 25 and body["fallback"] is False and body["errors"] == []
    hits = by_id(body)
    f1 = hits["F1"]
    assert f1["type"] == "file" and f1["snippet"] == "a Masterplan… & more x" and f1["driveId"] == OWN and f1["title"] == "Masterplan.xlsx"
    assert f1["from"] == {"displayName": "Ann", "email": "a@x.ch"} and f1["isFolder"] is False and f1["mimeType"] == "x/y"
    assert f1["location"] == {"path": "Deutsch/Prüfungen", "kind": "onedrive", "label": "OneDrive > Deutsch/Prüfungen"}
    assert hits["F2"]["location"]["kind"] == "team" and hits["F2"]["location"]["teamName"] == "BM23d ab 2025"
    assert hits["F2"]["location"]["channelName"] == "Deutsch" and hits["F2"]["location"]["channelId"] == CH
    assert hits["F2"]["location"]["label"] == "Team BM23d ab 2025 > Deutsch/Prüfungen"
    assert hits["F3"]["location"]["kind"] == "shared"
    assert hits["F4"]["location"]["kind"] == "sharepoint" and hits["F4"]["location"]["path"] is None
    assert hits["M1"]["location"] == {"kind": "mailbox", "label": "Mailbox"} and hits["M1"]["from"] == {"displayName": "Bob", "email": "b@x.ch"}
    assert hits["C1"]["type"] == "channel" and hits["C1"]["location"]["channelName"] == "Deutsch" and hits["C1"]["location"]["teamId"] == TEAM
    assert hits["C2"]["type"] == "chat" and hits["C2"]["location"]["chatId"] == "19:chat@unq.gbl.spaces"
    assert not any(k.startswith("_") for h in body["hits"] for k in h)


def test_type_filters_and_team_filter(env):
    note, client = env
    body = client.post("/api/search", json={"q": "x", "types": ["mail"]}, headers=H).json()
    assert [h["id"] for h in body["hits"]] == ["M1"] and note.posts[0]["entityTypes"] == ["message"]
    body = client.post("/api/search", json={"q": "x", "types": ["chats"]}, headers=H).json()
    assert [h["id"] for h in body["hits"]] == ["C2"]
    body = client.post("/api/search", json={"q": "x", "types": ["channels", "mail"], "teamId": TEAM}, headers=H).json()
    assert [h["id"] for h in body["hits"] if h["type"] != "file"] == ["C1"]


def test_files_search_only_files_and_paging_params(env):
    note, client = env
    body = client.post("/api/files/search", json={"q": "x", "from": 50, "size": 10}, headers=H).json()
    assert {h["type"] for h in body["hits"]} == {"file"} and len(note.posts) == 1
    assert note.posts[0]["from"] == 50 and note.posts[0]["size"] == 10 and body["nextFrom"] == 60


def test_team_scoped_file_search_uses_the_library(env):
    note, client = env
    body = client.post("/api/files/search", json={"q": "it\'s", "teamId": TEAM}, headers=H).json()
    assert not note.posts and "it%27%27s" in note.drive_searches[0] and note.drive_searches[0].startswith("drives/b%21TEAM/root/search")
    assert body["hits"][0]["location"]["kind"] == "team" and body["hits"][0]["location"]["path"] == "Deutsch"


def test_failing_source_never_fails_the_search(env):
    note, client = env
    note.msg_error = GraphError(403, "no")
    body = client.post("/api/search", json={"q": "x"}, headers=H).json()
    assert body["errors"] == ["messages: not permitted (403)"] and any(h["type"] == "file" for h in body["hits"])
    note.msg_error = None
    note.file_error = GraphError(404, "x")
    body = client.post("/api/search", json={"q": "x"}, headers=H).json()
    assert body["errors"] == ["files: request refused (404)"] and body["fallback"] is False and body["hits"]
    note.msg_error = GraphError(500, "x")
    body = client.post("/api/search", json={"q": "x", "types": ["files", "mail"]}, headers=H).json()
    assert body["errors"] == ["files: request refused (404)", "mail: service error (500)"] and body["hits"] == []


def test_path_lookup_failure_only_drops_the_path(env):
    note, client = env
    note.batch_fail = True
    body = client.post("/api/files/search", json={"q": "x"}, headers=H).json()
    assert by_id(body)["F1"]["location"]["kind"] == "onedrive" and by_id(body)["F1"]["location"]["path"] is None


@pytest.mark.parametrize("status", [400, 403, 503])
def test_fallback_searches_own_drive_and_team_libraries(env, status):
    note, client = env
    note.file_error = GraphError(status, "refused")
    body = client.post("/api/files/search", json={"q": "plan"}, headers=H).json()
    assert body["fallback"] is True and body["errors"] == []
    assert len(note.drive_searches) == 2 and note.drive_searches[0].startswith("me/drive/root/search")
    assert {h["location"]["kind"] for h in body["hits"]} == {"onedrive", "team"}
    note.team_search_fails = True
    body = client.post("/api/files/search", json={"q": "plan"}, headers=H).json()
    assert body["fallback"] is True and body["errors"] == ["files: 1 of 2 libraries could not be searched"] and len(body["hits"]) == 1


@pytest.mark.parametrize("payload", [{"q": ""}, {"q": "   "}, {"q": "secretquery" * 30}, {"q": "secretquery", "size": 0}, {"q": "secretquery", "size": 51}, {"q": "secretquery", "from": -1}, {"q": "secretquery", "types": ["calendar"]}, {"q": "secretquery", "types": []}])
def test_bad_bodies_are_422_and_never_echo_the_query(env, payload):
    _, client = env
    r = client.post("/api/search", json=payload, headers=H)
    assert r.status_code == 422 and "secretquery" not in r.text and "input" not in r.text


def test_bad_team_id_is_400(env):
    note, client = env
    assert client.post("/api/search", json={"q": "x", "teamId": "../x"}, headers=H).status_code == 400
    assert not note.posts
